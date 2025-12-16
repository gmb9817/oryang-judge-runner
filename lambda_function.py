import sys
import subprocess
import json
import time
import resource
import os
import signal

def handler(event, context):
    """
    AWS Lambda Online Judge Handler (Optimized)
    기능: 파일 기반 I/O를 통한 대용량 입력 처리, C++17 지원, 안정성 강화
    """
    
    # 1. 입력 데이터 파싱
    if isinstance(event, str):
        body = json.loads(event)
    else:
        body = event

    code = body.get('code', '')
    language = body.get('language', 'python') # 'python' or 'cpp'
    input_data = body.get('input', '')
    
    # 타임아웃 설정 (기본 2초 -> 안전하게 처리)
    time_limit = body.get('time_limit', 2) 

    result = {
        'output': '', 
        'status': 'success',
        'time': 0,    # ms
        'memory': 0   # KB
    }

    # /tmp 디렉토리 경로 설정
    source_path = ""
    exe_path = ""
    input_file_path = "/tmp/input.txt" # 입력을 저장할 파일 경로

    try:
        # ==========================================
        # [최적화] 입력 데이터를 파일로 저장
        # 메모리 절약 및 파이프(Pipe) 데드락 방지
        # ==========================================
        with open(input_file_path, "w") as f:
            f.write(input_data)

        # ==========================================
        # 2. 컴파일 단계 (C++만 해당)
        # ==========================================
        if language == 'cpp':
            source_path = "/tmp/solution.cpp"
            exe_path = "/tmp/solution"
            
            with open(source_path, "w") as f:
                f.write(code)

            compile_cmd = [
                "g++", source_path, 
                "-o", exe_path, 
                "-O2", 
                "-static",
                "-Wall", 
                "-lm", 
                "-std=gnu++17" # C++17 지원
            ]
            
            compile_proc = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True
            )

            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
                return {'statusCode': 200, 'body': json.dumps(result)}

        # ==========================================
        # 3. 실행 단계 (파일 스트림 사용)
        # ==========================================
        
        run_cmd = []
        if language == 'python':
            run_cmd = [sys.executable, "-c", code]
        elif language == 'cpp':
            run_cmd = [exe_path]

        start_time = time.time()
        
        try:
            # [핵심 수정] stdin=infile을 사용하여 파이프 대신 파일 내용을 직접 주입
            with open(input_file_path, "r") as infile:
                process = subprocess.run(
                    run_cmd,
                    stdin=infile,        # input=input_data 대신 파일 스트림 사용
                    capture_output=True, # stdout/stderr 캡처
                    text=True,
                    timeout=time_limit
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
            
            # 메모리 측정 (최대 RSS)
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            result['memory'] = int(usage.ru_maxrss) 

            if process.returncode != 0:
                result['status'] = 'runtime_error'
                
                if process.stderr:
                    err_msg = process.stderr.strip()
                    if len(err_msg) > 1024:
                        err_msg = err_msg[:1024] + "\n... (Error truncated)"
                    result['output'] = err_msg
                else:
                    # Signal 분석
                    code = -process.returncode
                    if code == signal.SIGSEGV:
                        result['output'] = "Runtime Error (Segmentation Fault)"
                    elif code == signal.SIGFPE:
                        result['output'] = "Runtime Error (Floating Point Exception)"
                    elif code == signal.SIGABRT:
                        result['output'] = "Runtime Error (Aborted)"
                    else:
                        result['output'] = f"Runtime Error (Exit Code: {process.returncode})"
            else:
                output_str = process.stdout.strip() if process.stdout else ""
                if len(output_str) > 65535:
                    output_str = output_str[:65535] + "\n... (Output truncated)"
                result['output'] = output_str

    except Exception as e:
        result['status'] = 'server_error'
        result['output'] = f"System Error: {str(e)}"
    
    # ==========================================
    # 5. 청소 (Clean up)
    # ==========================================
    for path in [exe_path, source_path, input_file_path]:
        if path and os.path.exists(path):
            try: os.remove(path)
            except: pass

    return {
        'statusCode': 200,
        'body': json.dumps(result)
    }
