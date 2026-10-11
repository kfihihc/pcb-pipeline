Open in a browser over HTTP (file:// does not work):
  python3 -m http.server --directory s3 8000
  then http://localhost:8000/   (any free port; Ctrl+C stops the server)
