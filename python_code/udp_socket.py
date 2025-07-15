import socket

buffer_bytes = 1024
class UDPSocket:

    def __init__(self, address):
        # address = (ip, port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(address)
        self.socket.settimeout(.02)
        # print(f'Listening to UDP port: {address[1]}')
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.socket.close()
        return True

    def receive(self):
        try:
            msg, address = self.socket.recvfrom(buffer_bytes)
            return True, msg.decode(), address
        except socket.timeout:
            return False, None, None

    def send(self, msg, address):
        # address = (ip, port)
        self.socket.sendto(msg.encode('ascii'),address)