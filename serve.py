"""Local dev server for PWA testing on LAN."""
import http.server
import socketserver
import socket
import os

PORT = 8000
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_mockups")
os.chdir(DIR)

handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
    ip = socket.gethostbyname(socket.gethostname())
    print(f"Serving app_mockups/ at http://{ip}:{PORT}")
    print(f"Press Ctrl+C to stop")
    httpd.serve_forever()
