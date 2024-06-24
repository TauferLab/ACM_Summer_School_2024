import http.server

class MyHttpServer(http.server.SimpleHTTPRequestHandler):
	
	def end_headers(self):
		self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
		self.send_header("Pragma", "no-cache")
		self.send_header("Expires", "0")
		super().end_headers()


if __name__ == '__main__':
	# NOTE: I am disabling cache in http.server (useful for debugging mode)
	http.server.test(HandlerClass=MyHttpServer)