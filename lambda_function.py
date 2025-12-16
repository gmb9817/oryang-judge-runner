import sys
import subprocess
import json
import time
import resource
import os
import signal
import stat

def handler(event, context):
    # 1. 입력 데이터 파싱
    if isinstance(event, str):
        body = json.loads(event)
    else:
        body = event

    code = body.get('code', '')
    language = body.get('language', 'python')
    input_data = body.get('input', '')
    time_limit = body.get('time_limit', 2)

    result = {
        'output': '',
        'status': 'success',
        'time': 0,
        'memory': 0
    }

    # 파일 경로 정의
    input_file_path = "/tmp/input.txt"
    source_path = ""
    exe_path = ""

    # 환경 변수 설정 (C++ 컴파일러 안정성 위함)
    env = os.environ.copy()
    env['HOME'] = '/tmp'

    try:
        # [준비] 입력 데이터 파일로 저장
        with open(input_file_path, "w") as f:
            f.write(input_data)

        run_cmd = []

        # ==========================================
        # 2. 언어별 파일 생성 (있는 그대로 저장)
        # ==========================================
        if language == 'python':
            source_path = "/tmp/solution.py"
            # [핵심] 사용자가 준 코드를 수정 없이 그대로 파일에 씀
            with open(source_path, "w") as f:
                f.write(code)
            
            # 파일 실행 (python -c 대신 파일 경로 실행)
            run_cmd = [sys.executable, source_path]

        elif language == 'cpp':
            source_path = "/tmp/solution.cpp"
            exe_path = "/tmp/solution"
            
            with open(source_path, "w") as f:
                f.write(code)

            # C++ 컴파일 (-static 제거하여 호환성 확보)
            compile_cmd = [
                "/usr/bin/g++", source_path,
                "-o", exe_path,
                "-O2", "-Wall", "-lm", "-std=gnu++17"
            ]
            
            # 컴파일 실행
            compile_proc = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                env=env
            )

            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
                return {'statusCode': 200, 'body': json.dumps(result)}
            
            # 실행 권한 부여 (Permission denied 방지)
            if os.path.exists(exe_path):
                os.chmod(exe_path, os.stat(exe_path).st_mode | stat.S_IEXEC)

            run_cmd = [exe_path]

        # ==========================================
        # 3. 코드 실행
        # ==========================================
        start_time = time.time()
        
        try:
            with open(input_file_path, "r") as infile:
                process = subprocess.run(
                    run_cmd,
                    stdin=infile,        # 입력 파일 내용을 stdin으로 주입
                    capture_output=True, # 출력 캡처
                    text=True,
                    timeout=time_limit,
                    env=env
                )
            is_timeout = False
        except subprocess.TimeoutExpired:
            is_timeout = True
            process = None

        end_time = time.time()

        # ==========================================
        # 4. 결과 정리
        # ==========================================
        if is_timeout:
            result['status'] = 'timeout'
            result['output'] = 'Time Limit Exceeded'
            result['time'] = int(time_limit * 1000)
        else:
            result['time'] = int((end_time - start_time) * 1000)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            result['memory'] = int(usage.ru_maxrss)

            if process.returncode != 0:
                result['status'] = 'runtime_error'
                result['output'] = process.stderr if process.stderr else "Runtime Error"
            else:
                result['output'] = process.stdout

    except Exception as e:
        result['status'] = 'server_error'
        result['output'] = str(e)

    # 정리 (파일 삭제)
    for path in [exe_path, source_path, input_file_path]:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
