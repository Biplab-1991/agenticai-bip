import paramiko
from langchain_core.runnables import Runnable

class SysAdminExecutor(Runnable):
    def __init__(self, ssh_host, username, private_key_path):
        self.ssh_host = ssh_host
        self.username = username
        self.private_key_path = private_key_path

    def invoke(self, state: dict) -> dict:
        plan = state.get("plan", {})
        commands = plan.get("commands", [])
        result = {
            "status": "skipped",
            "output": "",
            "error": ""
        }

        if not commands:
            result["output"] = "No commands to execute."
        else:
            try:
                # Load SSH private key
                key = paramiko.RSAKey.from_private_key_file(self.private_key_path)

                # Connect to the VM
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=self.ssh_host, username=self.username, pkey=key)

                output = ""
                for cmd in commands:
                    stdin, stdout, stderr = ssh.exec_command(cmd)
                    stdout_text = stdout.read().decode()
                    stderr_text = stderr.read().decode()
                    output += f"\n$ {cmd}\n{stdout_text}"
                    if stderr_text:
                        output += f"\n⚠️ STDERR:\n{stderr_text}"

                ssh.close()
                result["status"] = "success"
                result["output"] = output

            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)

        state["execution_result"] = result
        return state
