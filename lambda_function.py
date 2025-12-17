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
        # 1. 파라미터 파싱
        code = event.get('code', '')
        language = event.get('language', 'c').lower()
        s3_key = event.get('s3_key')
        base_time_limit = float(event.get('time_limit', 1.0))
        memory_limit_mb = int(event.get('memory_limit', 128))
        
        input_file_path = '/tmp/input.txt'
        output_file_path = '/tmp/stdout.txt'
        error_file_path = '/tmp/stderr.txt'
        
        # 2. 입력 데이터 준비 (S3에서 직접 다운로드하여 메모리 보호)
        if s3_key:
            s3.download_file(BUCKET_NAME, s3_key, input_file_path)
        else:
            with open(input_file_path, 'wb') as f: # 바이너리 모드로 저장
                f.write(event.get('input', '').encode('utf-8'))

        # 3. 실행 환경 및 커맨드 설정
        run_cmd = []
        if language in ['python', 'py']:
            file_name = '/tmp/solution.py'
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write("import sys; sys.setrecursionlimit(10**6);\n" + code)
            run_cmd = [sys.executable, '-u', file_name]
        elif language in ['c', 'cpp']:
            ext = 'c' if language == 'c' else 'cpp'
            compiler = 'gcc' if language == 'c' else 'g++'
            file_name = f'/tmp/solution.{ext}'
            exe = '/tmp/solution'
            with open(file_name, 'w', encoding='utf-8') as f: f.write(code)
            # 컴파일 (컴파일 단계는 메모리 제한을 크게 받지 않음)
            subprocess.run([compiler, '-O2', file_name, '-o', exe], check=True, capture_output=True)
            run_cmd = [exe]

        # 4. 리소스 제한 (RLIMIT_AS 대신 물리 메모리 관리에 집중)
        def set_limits():
            # 가상 메모리(AS) 대신 실제 데이터 영역(DATA)과 파일 크기(FSIZE) 제한
            # 사용자 프로그램이 50MB 이상의 파일을 생성하지 못하게 제한
            max_file_size = 50 * 1024 * 1024 
            resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_size, max_file_size))
            # 메모리 제한은 넉넉하게 주되, 람다 전체 용량을 넘지 않게 설정
            limit_bytes = memory_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_DATA, (limit_bytes, limit_bytes))

        # 5. 실행 (핵심: text=False로 설정하여 바이너리 스트리밍)
        start_time = time.time()
        
        with open(input_file_path, 'rb') as infile, \
             open(output_file_path, 'wb') as outfile, \
             open(error_file_path, 'wb') as errfile:
            
            process = subprocess.Popen(
                run_cmd,
                stdin=infile,
                stdout=outfile,
                stderr=errfile,
                text=False, # 바이너리 모드로 전환 (메모리 복사 방지)
                preexec_fn=set_limits
            )
            
            try:
                # 실제 타임아웃 계산 (여유시간 포함)
                actual_timeout = (base_time_limit * 3 + 2) if 'py' in language else base_time_limit
                process.wait(timeout=actual_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return {'statusCode': 200, 'body': json.dumps({'status': 'timeout'})}

        time_used = int((time.time() - start_time) * 1000)
        
        # 6. 결과 파일 읽기 (제한된 크기만 메모리에 로드)
        output_data = ""
        if os.path.exists(output_file_path):
            with open(output_file_path, 'rb') as f:
                output_data = f.read(1024 * 1024).decode('utf-8', errors='ignore').strip()
            
        stderr_data = ""
        if os.path.exists(error_file_path):
            with open(error_file_path, 'rb') as f:
                stderr_data = f.read(2048).decode('utf-8', errors='ignore')

        # 7. 종료 상태 확인
        if process.returncode != 0:
            status = 'runtime_error'
            if process.returncode == -9: status = 'memory_limit_exceeded'
            return {'statusCode': 200, 'body': json.dumps({'status': status, 'output': stderr_data})}

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
        return {'statusCode': 200, 'body': json.dumps({'status': 'judge_error', 'output': traceback.format_exc()})}
