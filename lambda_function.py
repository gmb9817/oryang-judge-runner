import json
import os
import subprocess
import boto3
import time
import resource
import sys
import traceback

s3 = boto3.client('s3')
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME', 'oryang-judge-tc')

def lambda_handler(event, context):
    # 클린업 파일 리스트
    temp_files = [
        '/tmp/input.txt', '/tmp/stdout.txt', '/tmp/stderr.txt', 
        '/tmp/solution', '/tmp/solution.c', '/tmp/solution.cpp', '/tmp/solution.py'
    ]

    # 결과 변수 초기화
    memory_limit_mb = 128
    
    try:
        # --- 1. 파라미터 파싱 ---
        code = event.get('code', '')
        language = event.get('language', 'c').lower()
        s3_key = event.get('s3_key')
        base_time_limit = float(event.get('time_limit', 1.0))
        memory_limit_mb = int(event.get('memory_limit', 128))
        
        input_file_path = '/tmp/input.txt'
        output_file_path = '/tmp/stdout.txt'
        error_file_path = '/tmp/stderr.txt'
        
        # --- 2. 입력 데이터 준비 (S3 -> File) ---
        # 메모리를 아끼기 위해 변수에 담지 않고 바로 파일로 씁니다.
        if s3_key:
            s3.download_file(BUCKET_NAME, s3_key, input_file_path)
        else:
            # 입력값이 문자열로 들어온 경우 바이너리로 저장
            input_val = event.get('input', '')
            if isinstance(input_val, str):
                input_val = input_val.encode('utf-8')
            with open(input_file_path, 'wb') as f:
                f.write(input_val)

        # --- 3. 실행 커맨드 준비 ---
        run_cmd = []
        if language in ['python', 'py']:
            file_name = '/tmp/solution.py'
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write("import sys; sys.setrecursionlimit(10**6);\n" + code)
            run_cmd = [sys.executable, '-u', file_name]
            
        elif language in ['c', 'cpp']:
            is_cpp = (language == 'cpp')
            ext = 'cpp' if is_cpp else 'c'
            compiler = 'g++' if is_cpp else 'gcc'
            src_path = f'/tmp/solution.{ext}'
            exe_path = '/tmp/solution'
            
            with open(src_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 컴파일 실행
            comp_proc = subprocess.run(
                [compiler, '-O2', src_path, '-o', exe_path],
                capture_output=True, text=True
            )
            
            if comp_proc.returncode != 0:
                return {
                    'statusCode': 200, 
                    'body': json.dumps({
                        'status': 'compile_error', 
                        'output': comp_proc.stderr[:1000] # 에러 메시지 너무 길면 자름
                    })
                }
            run_cmd = [exe_path]

        # --- 4. 리소스 제한 (Docker 호환성 최우선) ---
        def set_limits():
            try:
                # 출력 파일 크기 제한 (50MB) - 디스크 꽉 참 방지
                limit_size = 50 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit_size, limit_size))
                
                # 프로세스 개수 제한 (좀비 프로세스 방지, 넉넉하게 64개)
                resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
                
                # ★ 중요: RLIMIT_AS(메모리 제한) 삭제 ★
                # Docker 환경에서 이 설정은 치명적인 Judge Error(권한 오류)를 유발합니다.
                # 메모리 제한은 AWS Lambda 설정(2048MB)에 맡깁니다.
                
            except Exception:
                # 여기서 에러나면 프로세스가 시작도 못하고 죽으므로 그냥 통과시킵니다.
                pass

        # --- 5. 프로세스 실행 ---
        start_time = time.time()
        
        with open(input_file_path, 'rb') as infile, \
             open(output_file_path, 'wb') as outfile, \
             open(error_file_path, 'wb') as errfile:
            
            process = subprocess.Popen(
                run_cmd,
                stdin=infile,
                stdout=outfile,
                stderr=errfile,
                text=False, # 바이너리 모드 (메모리 절약)
                preexec_fn=set_limits
            )
            
            try:
                # Python 넉넉한 시간, C/C++ 정배수 시간
                timeout_val = (base_time_limit * 3 + 2) if 'py' in language else base_time_limit
                process.wait(timeout=timeout_val)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait() # 좀비 회수
                return {
                    'statusCode': 200, 
                    'body': json.dumps({'status': 'timeout', 'time': int(timeout_val * 1000)})
                }

        time_used = int((time.time() - start_time) * 1000)
        
        # --- 6. 결과 읽기 (Truncate 적용) ---
        output_data = ""
        # 출력 결과가 너무 크면 앞부분 512KB만 읽음 (JSON 파싱 에러 및 메모리 방지)
        if os.path.exists(output_file_path):
            try:
                with open(output_file_path, 'rb') as f:
                    output_data = f.read(512 * 1024).decode('utf-8', errors='replace').strip()
            except Exception:
                output_data = ""

        stderr_data = ""
        if os.path.exists(error_file_path):
            try:
                with open(error_file_path, 'rb') as f:
                    stderr_data = f.read(1024).decode('utf-8', errors='replace')
            except Exception:
                stderr_data = ""

        # --- 7. 최종 상태 판별 ---
        if process.returncode != 0:
            # 리턴코드 분석
            status = 'runtime_error'
            if process.returncode == -9: status = 'memory_limit_exceeded' # SIGKILL
            if process.returncode == -24: status = 'output_limit_exceeded' # SIGXFSZ (파일크기초과)
            
            return {
                'statusCode': 200, 
                'body': json.dumps({'status': status, 'output': stderr_data})
            }

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'output': output_data,
                'time': time_used,
                'memory': memory_limit_mb # 참고용 표시
            })
        }

    except Exception as e:
        # ★ 여기가 가장 중요합니다 ★
        # Judge Error가 발생한 진짜 원인(Traceback)을 output에 담아 보냅니다.
        error_log = traceback.format_exc()
        print(f"CRITICAL ERROR: {error_log}") # CloudWatch 로그용
        return {
            'statusCode': 200, 
            'body': json.dumps({
                'status': 'judge_error', 
                'output': f"Internal Error: {str(e)}\nTrace: {error_log}" 
            })
        }
    
    finally:
        # 청소
        for f in temp_files:
            try:
                if os.path.exists(f): os.remove(f)
            except: pass
