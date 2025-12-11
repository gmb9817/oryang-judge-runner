import sys
import subprocess
import json

def handler(event, context):
    if isinstance(event, str): body = json.loads(event)
    else: body = event
    
    code = body.get('code', '')
    language = body.get('language', 'python')
    input_data = body.get('input', '')
    result = {'output': '', 'status': 'success'}

    try:
        if language == 'python':
            proc = subprocess.run([sys.executable, "-c", code], input=input_data, capture_output=True, text=True, timeout=2)
            result['output'] = proc.stdout.strip() if proc.returncode == 0 else proc.stderr
            if proc.returncode != 0: result['status'] = 'runtime_error'
            
        elif language == 'cpp':
            with open("/tmp/sol.cpp", "w") as f: f.write(code)
            compile_proc = subprocess.run(["g++", "/tmp/sol.cpp", "-o", "/tmp/sol"], capture_output=True, text=True)
            if compile_proc.returncode != 0:
                result['status'] = 'compile_error'
                result['output'] = compile_proc.stderr
            else:
                run_proc = subprocess.run(["/tmp/sol"], input=input_data, capture_output=True, text=True, timeout=2)
                result['output'] = run_proc.stdout.strip() if run_proc.returncode == 0 else run_proc.stderr
                if run_proc.returncode != 0: result['status'] = 'runtime_error'

    except Exception as e:
        result = {'status': 'error', 'output': str(e)}

    return {'statusCode': 200, 'body': json.dumps(result)}
