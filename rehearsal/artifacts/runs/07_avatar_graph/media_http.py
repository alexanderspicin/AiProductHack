"""Bounded local media responses with byte ranges and HEAD support."""
import mimetypes
import re


def byte_range(value, size):
    if not value: return 0, size-1, False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value.strip())
    if not match or not any(match.groups()):raise ValueError('Invalid range')
    first,last=match.groups()
    if not first:
        count=int(last)
        if count<=0:raise ValueError('Invalid suffix')
        return max(0,size-count),size-1,True
    start=int(first);end=min(int(last),size-1) if last else size-1
    if start>=size or start>end:raise ValueError('Unsatisfiable range')
    return start,end,True


def send_file(handler,file,head=False):
    size=file.stat().st_size
    try:start,end,partial=byte_range(None if head else handler.headers.get('Range'),size)
    except ValueError:
        handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}')
        handler.send_header('Content-Length','0');handler.end_headers();return
    handler.send_response(206 if partial else 200)
    handler.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
    handler.send_header('Accept-Ranges','bytes');handler.send_header('Content-Length',str(end-start+1))
    handler.send_header('X-Content-Type-Options','nosniff');handler.send_header('Cache-Control','no-cache')
    if partial:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.end_headers()
    if head:return
    try:
        with file.open('rb') as stream:
            stream.seek(start);remaining=end-start+1
            while remaining>0:
                chunk=stream.read(min(65536,remaining))
                if not chunk:break
                handler.wfile.write(chunk);remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError):pass
