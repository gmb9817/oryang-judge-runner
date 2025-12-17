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
    try:
        # --- 1. 파라미터 파싱 ---
        code = event.get('code', '')
        language = event.get('language', 'c')
        s3_key = event.get('s3_key')
        base_time_limit = float(event.get('time_limit', 1.0))
        memory_limit_mb = int(event.get('memory_limit', 128))
        
        input_file_path = '/tmp/input.txt'
        output_file_path = '/tmp/stdout.txt'
        error_file_path = '/tmp/stderr.txt'
        
        # --- 2. 입력 데이터 준비 ---
        if s3_key:
            s3.download_file(BUCKET_NAME, s3_key, input_file_path)
        else:
            with open(input_file_path, 'w', encoding='utf-8') as f:
                f.write(event.get('input', ''))

        # --- 3. 실행 커맨드 설정 ---
        run_cmd = []
        # 메모리: 설정값 * 2 + 64MB 여유 (Bytes 단위 변환)
        limit_as_bytes = (memory_limit_mb * 2 + 64) * 1024 * 1024
        
        # 시간: Python은 3배+2초 여유, C/C++은 그대로
        actual_time_limit = base_time_limit
        if language in ['python', 'py']:
            actual_time_limit = (base_time_limit * 3.0) + 2.0
        
        if language in ['python', 'py']:
            file_name = '/tmp/solution.py'
            # Python 재귀 제한만 해제 (시스템 스택은 건드리지 않음)
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write("import sys; sys.setrecursionlimit(10**6);\n" + code)
            run_cmd = [sys.executable, '-u', file_name]
            
        elif language == 'c':
            file_name = '/tmp/solution.c'
            exe = '/tmp/solution'
            with open(file_name, 'w', encoding='utf-8') as f: f.write(code)
            # 컴파일
            subprocess.run(['gcc', '-O2', file_name, '-o', exe], check=True)
            run_cmd = [exe]
            
        elif language == 'cpp':
            file_name = '/tmp/solution.cpp'
            exe = '/tmp/solution'
            with open(file_name, 'w', encoding='utf-8') as f: f.write(code)
            # 컴파일
            subprocess.run(['g++', '-O2', file_name, '-o', exe], check=True)
            run_cmd = [exe]

        # --- 4. 리소스 제한 함수 (안전 모드) ---
        def set_limits():
            try:
                # ★ [핵심 수정] 스택 제한 코드 삭제 (AWS Lambda에서 금지됨)
                # 메모리 제한만 설정 (Bytes 단위)
                if limit_as_bytes > 0:
                    resource.setrlimit(resource.RLIMIT_AS, (limit_as_bytes, limit_as_bytes))
            except Exception:
                sys.exit(100) # 설정 실패 시 종료 코드 100

        # --- 5. 실행 ---
        start_time = time.time()
        
        with open(input_file_path, 'r') as infile, \
             open(output_file_path, 'w') as outfile, \
             open(error_file_path, 'w') as errfile:
            
            process = subprocess.Popen(
                run_cmd,
                stdin=infile,
                stdout=outfile,
                stderr=errfile,
                text=True,
                preexec_fn=set_limits
            )
            
            try:
                process.wait(timeout=actual_time_limit)
            except subprocess.TimeoutExpired:
                process.kill()
                return {'statusCode': 200, 'body': json.dumps({'status': 'timeout', 'time': actual_time_limit * 1000})}

        time_used = int((time.time() - start_time) * 1000)
        
        # 출력 읽기
        output_data = ""
        if os.path.exists(output_file_path):
            with open(output_file_path, 'r', errors='ignore') as f: output_data = f.read(2048)
            
        stderr_data = ""
        if os.path.exists(error_file_path):
            with open(error_file_path, 'r', errors='ignore') as f: stderr_data = f.read(1024)

        # 결과 처리
        if process.returncode != 0:
            status = 'runtime_error'
            if process.returncode == -9: status = 'memory_limit_exceeded' # SIGKILL
            if process.returncode == 100: stderr_data += " [System] Resource Limit Failed"
            
            return {
                'statusCode': 200, 
                'body': json.dumps({'status': status, 'output': stderr_data})
            }
            
        # 시간 초과 2차 체크 (Python 여유 시간 제외하고 원본 시간과 비교)
        # Python은 시간이 넉넉하므로, 실제 사용 시간이 '원본 제한'을 넘었는지 확인
        display_time_limit = base_time_limit * 1000
        if language in ['python', 'py'] and time_used > display_time_limit:
             return {'statusCode': 200, 'body': json.dumps({'status': 'timeout', 'time': time_used})}

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'output': output_data,
                'time': time_used,
                'memory': memory_limit_mb
            })
        }

    except Exception:
        # 시스템 에러 발생 시 상세 로그 반환
        return {
            'statusCode': 200, 
            'body': json.dumps({'status': 'judge_error', 'output': traceback.format_exc()})
        }
