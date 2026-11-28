"""Seekable, bounded HTTP-range access to EPA's large ZIPs (including ZIP64).

zipfile validates the directory and each member's CRC. No whole-archive fallback:
an ignored range or a changed/truncated file fails the read, preserving feed history.
"""
from __future__ import annotations
import io


class RemoteZip(io.RawIOBase):
    def __init__(self, session, url, size, etag=None, last_modified=None, block_size=2_000_000):
        self.session, self.url, self.size = session, url, size
        self.etag, self.last_modified, self.block_size = etag, last_modified, block_size
        self.pos, self.block_start, self.block = 0, -1, b''
        self.downloaded = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        if whence not in (0, 1, 2) or pos < 0:
            raise ValueError('invalid ZIP seek')
        self.pos = pos
        return pos

    def read(self, size=-1):
        remaining = max(0, self.size - self.pos) if size < 0 else min(size, max(0, self.size - self.pos))
        chunks = []
        while remaining:
            start = self.pos // self.block_size * self.block_size
            if start != self.block_start:
                end = min(start + self.block_size, self.size) - 1
                headers = {'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'}
                if self.etag and not self.etag.startswith('W/'):
                    headers['If-Match'] = self.etag
                elif self.last_modified:
                    headers['If-Unmodified-Since'] = self.last_modified
                res = self.session.get(self.url, headers=headers, timeout=(20, 120), stream=True)
                try:
                    res.raise_for_status()
                    if res.status_code != 206 or res.headers.get('Content-Range') != f'bytes {start}-{end}/{self.size}':
                        raise ValueError('EPA ZIP range was not honored')
                    parts, count = [], 0
                    for part in res.iter_content(64 * 1024):
                        count += len(part)
                        if count > end - start + 1:
                            raise ValueError('EPA ZIP range exceeded requested size')
                        parts.append(part)
                    if count != end - start + 1:
                        raise ValueError('EPA ZIP range was truncated')
                    self.block = b''.join(parts)
                    self.block_start = start
                    self.downloaded += count
                finally:
                    res.close()
            offset = self.pos - start
            n = min(remaining, len(self.block) - offset)
            chunks.append(self.block[offset:offset+n])
            self.pos += n
            remaining -= n
        return b''.join(chunks)
