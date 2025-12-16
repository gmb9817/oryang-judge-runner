import sys
import subprocess
import json
import time
import resource
import os
import signal
import stat

def handler(event, context):
    """
    AWS Lambda Online Judge Handler (Final Fix)
    - Fix: -static 옵션 제거 (AL2023 호환성 문제 해결)
    - Fix: 실행 권한(chmod +x) 명시적 부여
    - Fix: 환경 변수(HOME) 설정
    """
    
    # 1. 입력 데이터 파싱
    if isinstance(event, str):
        body = json.loads(event)
    else:
        body = event

    code = body.get('code', '')
    # [방어 코드] 눈에 안 보이는 특수문자 제거
    if code:
        code = code.replace('\u00a0', ' ').replace('\u3000', ' ')

    language = body.get('language', 'python') 
    input_data = body.get('input', '')
    time_limit = body.get('time_limit', 2) 

    result = {
        'output': '', 
        'status': 'success',
        'time': 0,    
        'memory': 0   
    }

    # 경로 설정
    source_path = ""
    exe_path = ""
    input_file_path = "/tmp/input.txt"

    # [중요] C++ 컴파일러를 위한 환경 변수 설정
    # HOME 변수가 없으면 g++이 가끔 경고를 뱉거나 실패할 수 있음
    env = os.environ.copy()
    env['HOME'] = '/tmp'

    try:
        # 입력 데이터 저장
        with open(input_file_path, "w") as f:
            f.write(input_data)

        run_cmd = []

        # ==========================================
        # 2. 언어별 처리
        # ==========================================
        if language == 'python':
            source_path = "/tmp/solution.py"
            with open(source_path, "w") as f:
                f.write(code)
            run_cmd = [sys.executable, source_path]

        elif language == 'cpp':
            source_path = "/tmp/solution.cpp"
            exe_path = "/tmp/solution"
            
            with open(source_path, "w") as f:
                f.write(code)

            # [핵심 수정 1] -static 제거 (환경 호환성 해결)
            compile_cmd = [
                "/usr/bin/g++", source_path,  # 절대 경로 사용 권장
                "-o", exe_path, 
                "-O2", 
                "-Wall", 
                "-lm", 
                "-std=gnu++17" 
            ]
            
            compile_proc = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                env=env # 환경 변수 주입
            )

            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
                return {'statusCode': 200, 'body': json.dumps(result)}
            
            # [핵심 수정 2] 실행 권한 부여
            if os.path.exists(exe_path):
                os.chmod(exe_path, os.stat(exe_path).st_mode | stat.S_IEXEC)

            run_cmd = [exe_path]

        # ==========================================
        # 3. 실행 단계
        # ==========================================
        start_time = time.time()
        
        try:
            with open(input_file_path, "r") as infile:
                process = subprocess.run(
                    run_cmd,
                    stdin=infile,
                    capture_output=True,
                    text=True,
                    timeout=time_limit,
                    env=env # 환경 변수 주입
                )
            is_timeout = False
        except subprocess.TimeoutExpired:
            is_timeout = True
            process = None

        end_time = time.time()

        # ==========================================
        # 4. 결과 분석
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
                if process.stderr:
                    result['output'] = process.stderr[:1024]
                else:
                    # 시그널 분석
                    code = -process.returncode
                    if code == signal.SIGSEGV: result['output'] = "Runtime Error (Segmentation Fault)"
                    elif code == signal.SIGFPE: result['output'] = "Runtime Error (Floating Point Exception)"
                    elif code == signal.SIGABRT: result['output'] = "Runtime Error (Aborted)"
                    else: result['output'] = f"Runtime Error (Exit Code: {process.returncode})"
            else:
                out = process.stdout.strip() if process.stdout else ""
                result['output'] = out[:65535]

    except Exception as e:
        result['status'] = 'server_error'
        result['output'] = f"System Error: {str(e)}"
    
    # 청소
    for path in [exe_path, source_path, input_file_path]:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
