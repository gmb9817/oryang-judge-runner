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

# PyPy 실행 파일 경로 (Dockerfile에서 설치한 경로)
PYPY_PATH = '/usr/bin/pypy3'

def lambda_handler(event, context):
    # 클린업 파일 리스트
    temp_files = [
        '/tmp/input.txt', '/tmp/stdout.txt', '/tmp/stderr.txt', 
        '/tmp/solution', '/tmp/solution.c', '/tmp/solution.cpp', '/tmp/solution.py'
    ]

    try:
        # --- 1. 파라미터 파싱 ---
        code = event.get('code', '')
        language = event.get('language', 'c').lower()
        s3_key = event.get('s3_key')
        base_time_limit = float(event.get('time_limit', 1.0))
        # memory_limit는 여기서 프로세스 제한용으로 쓰지 않고(Docker 이슈), 참고용으로만 받음
        
        input_file_path = '/tmp/input.txt'
        output_file_path = '/tmp/stdout.txt'
        error_file_path = '/tmp/stderr.txt'
        
        # --- 2. 입력 데이터 준비 (S3 -> File) ---
        if s3_key:
            s3.download_file(BUCKET_NAME, s3_key, input_file_path)
        else:
            input_val = event.get('input', '')
            if isinstance(input_val, str):
                input_val = input_val.encode('utf-8')
            with open(input_file_path, 'wb') as f:
                f.write(input_val)

        # --- 3. 실행 커맨드 준비 ---
        run_cmd = []
        if language in ['python', 'py']:
            file_name = '/tmp/solution.py'
            # PyPy/Python 재귀 깊이 설정 추가
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write("import sys; sys.setrecursionlimit(200000);\n" + code)
            
            # [수정] sys.executable(CPython) 대신 PyPy 경로 사용
            # PyPy가 없으면 fallback으로 기본 python 사용
            executable = PYPY_PATH if os.path.exists(PYPY_PATH) else sys.executable
            run_cmd = [executable, '-u', file_name]
            
        elif language in ['c', 'cpp']:
            is_cpp = (language == 'cpp')
            ext = 'cpp' if is_cpp else 'c'
            compiler = 'g++' if is_cpp else 'gcc'
            src_path = f'/tmp/solution.{ext}'
            exe_path = '/tmp/solution'
            
            with open(src_path, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 컴파일 (최적화 옵션 -O2)
            comp_proc = subprocess.run(
                [compiler, '-O2', src_path, '-o', exe_path],
                capture_output=True, text=True
            )
            
            if comp_proc.returncode != 0:
                return {
                    'statusCode': 200, 
                    'body': json.dumps({
                        'status': 'compile_error', 
                        'output': comp_proc.stderr[:2000] 
                    })
                }
            run_cmd = [exe_path]

        # --- 4. 리소스 제한 설정 함수 ---
        def set_limits():
            try:
                # 출력 파일 크기 제한 (64MB)
                limit_size = 64 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (limit_size, limit_size))
                # 프로세스 생성 제한
                resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
            except Exception:
                pass

        # --- 5. 프로세스 실행 및 시간/메모리 측정 ---
        # S3 다운로드 등이 끝난 직후, 순수 실행 시간 측정 시작
        start_time = time.time()
        
        with open(input_file_path, 'rb') as infile, \
             open(output_file_path, 'wb') as outfile, \
             open(error_file_path, 'wb') as errfile:
            
            process = subprocess.Popen(
                run_cmd,
                stdin=infile,
                stdout=outfile,
                stderr=errfile,
                text=False,
                preexec_fn=set_limits
            )
            
            try:
                # Python(PyPy)은 JIT 워밍업 때문에 시간을 좀 더 넉넉히 줌 (기본 3배+2초)
                timeout_val = (base_time_limit * 3 + 2) if 'py' in language else base_time_limit
                process.wait(timeout=timeout_val)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait() # 좀비 프로세스 회수
                return {
                    'statusCode': 200, 
                    'body': json.dumps({'status': 'timeout', 'time': int(timeout_val * 1000)})
                }

        # 실행 시간 계산 (ms)
        time_used = int((time.time() - start_time) * 1000)

        # [수정] 실제 메모리 사용량 측정 (KB 단위)
        # getrusage는 자식 프로세스의 최대 RSS를 반환함 (Linux: KB, Mac: Byte)
        # Lambda는 Linux 환경이므로 KB 단위로 반환됨.
        rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        memory_used_kb = int(rusage.ru_maxrss) 

        # --- 6. 결과 읽기 ---
        output_data = ""
        if os.path.exists(output_file_path):
            try:
                with open(output_file_path, 'rb') as f:
                    output_data = f.read(512 * 1024).decode('utf-8', errors='replace').strip()
            except Exception: pass

        stderr_data = ""
        if os.path.exists(error_file_path):
            try:
                with open(error_file_path, 'rb') as f:
                    stderr_data = f.read(2048).decode('utf-8', errors='replace')
            except Exception: pass

        # --- 7. 최종 상태 판별 ---
        status = 'success'
        if process.returncode != 0:
            status = 'runtime_error'
            # 137(128+9) = SIGKILL, 139(128+11) = SIGSEGV 등
            if process.returncode == -9 or process.returncode == 137: status = 'memory_limit_exceeded'
            if process.returncode == -24 or process.returncode == 153: status = 'output_limit_exceeded' 
            
            return {
                'statusCode': 200, 
                'body': json.dumps({
                    'status': status, 
                    'output': stderr_data if stderr_data else f"Runtime Error (Return Code: {process.returncode})"
                })
            }

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'output': output_data,
                'time': time_used,
                'memory': memory_used_kb  # 실제 사용된 KB 단위 메모리
            })
        }

    except Exception as e:
        error_log = traceback.format_exc()
        print(f"CRITICAL ERROR: {error_log}")
        return {
            'statusCode': 200, 
            'body': json.dumps({
                'status': 'judge_error', 
                'output': f"Internal Error: {str(e)}\nTrace: {error_log}" 
            })
        }
    
    finally:
        # 파일 정리
        for f in temp_files:
            try:
                if os.path.exists(f): os.remove(f)
            except: pass
