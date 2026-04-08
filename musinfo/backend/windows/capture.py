import socket


WSL_HOST = "172.29.28.224"
WSL_PORT     = 5006

    # Opens a TCP connection to the WSL receiver and sends the "activate" command.
def send_activate():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((WSL_HOST, WSL_PORT))
            s.sendall(b"activate")
            print(f"[capture.py] Sent 'activate' to {WSL_HOST}:{WSL_PORT}")
    except ConnectionRefusedError:
        # receiver is not running
        print(f"[capture.py] Connection refused — is the WSL receiver running on port {WSL_PORT}?")
    except Exception as e:
        print(f"[capture.py] Error: {e}")

if __name__ == "__main__":
    send_activate()