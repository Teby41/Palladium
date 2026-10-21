/import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, clean_html, int_or_none, traverse_obj, url_or_none

_MEDIA_KEYS = ('video_versions', 'image_versions2', 'carousel_media')


class ThreadsPluginIE(InfoExtractor):
    IE_NAME = 'threads'
    IE_DESC = 'Threads (Meta): videos, imagenes y carruseles'
    _VALID_URL = (
        r'https?://(?:www\.)?threads\.(?:net|com)/'
        r'(?:@(?P<uploader_id>[^/?#]+)/post|t)/(?P<id>[\w-]+)')

    _HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
            '(KHTML, like Gecko) Version/17.0 Safari/605.1.15'),
        'Accept-Language': 'en-US,en;q=0.9',
    }

    # ---------- utilidades ----------

    def _iter_json_blobs(self, webpage):
        for m in re.finditer(
                r'<script[^>]+type="application/json"[^>]*>(.+?)</script>', webpage, re.S):
            data = self._parse_json(m.group(1), None, fatal=False)
            if data:
                yield data

    @staticmethod
    def _find_post(obj, post_id):
        """Busca (sin recursion) el dict del post cuyo 'code' sea post_id y que tenga media."""
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if cur.get('code') == post_id and any(cur.get(k) for k in _MEDIA_KEYS):
                    return cur
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
        return None

    def _formats_from_item(self, item):
        """Devuelve (formats, is_video) para un item de media."""
        videos = [v for v in (item.get('video_versions') or []) if url_or_none(v.get('url'))]
        if videos:
            width, height = int_or_none(item.get('original_width')), int_or_none(item.get('original_height'))
            formats = [{
                'url': v['url'],
                'format_id': f'video-{v.get("type", i)}',
                'ext': 'mp4',
                'width': width,
                'height': height,
                'quality': len(videos) - i,  # la API lista primero la mejor calidad
            } for i, v in enumerate(videos)]
            return formats, True

        candidates = [c for c in traverse_obj(item, ('image_versions2', 'candidates')) or []
                      if url_or_none(c.get('url'))]
        candidates.sort(key=lambda c: (c.get('width') or 0) * (c.get('height') or 0), reverse=True)
        formats = [{
            'url': c['url'],
            'format_id': f'image-{c.get("width")}x{c.get("height")}',
            'ext': 'jpg',
            'width': int_or_none(c.get('width')),
            'height': int_or_none(c.get('height')),
            'quality': len(candidates) - i,
        } for i, c in enumerate(candidates)]
        return formats, False

    # ---------- extraccion ----------

    def _real_extract(self, url):
        post_id, url_user = self._match_valid_url(url).group('id', 'uploader_id')
        webpage = self._download_webpage(url, post_id, headers=self._HEADERS)

        post = None
        for blob in self._iter_json_blobs(webpage):
            post = self._find_post(blob, post_id)
            if post:
                break

        if not post:
            return self._extract_from_opengraph(webpage, post_id, url_user)

        uploader = traverse_obj(post, ('user', 'username')) or url_user
        caption = traverse_obj(post, ('caption', 'text')) or ''
        common = {
            'uploader': uploader,
            'uploader_id': uploader,
            'channel': traverse_obj(post, ('user', 'full_name')),
            'description': caption,
            'timestamp': int_or_none(post.get('taken_at')),
            'like_count': int_or_none(post.get('like_count')),
            'webpage_url': url,
        }
        title = (clean_html(caption).split('\n')[0][:80] if caption else '') or f'Threads post {post_id}'
        title = f'{uploader} - {title}' if uploader else title

        items = post.get('carousel_media') or [post]
        entries = []
        for n, item in enumerate(items, 1):
            formats, is_video = self._formats_from_item(item)
            if not formats:
                continue
            entries.append({
                **common,
                'id': post_id if len(items) == 1 else f'{post_id}_{n}',
                'title': title if len(items) == 1 else f'{title} ({n})',
                'formats': formats,
                'thumbnail': traverse_obj(item, ('image_versions2', 'candidates', 0, 'url')),
                'ext': 'mp4' if is_video else 'jpg',
            })

        if not entries:
            raise ExtractorError('Este post de Threads no tiene video ni imagenes', expected=True)
        if len(entries) == 1:
            return entries[0]
        return self.playlist_result(entries, post_id, title, caption, **common)

    def _extract_from_opengraph(self, webpage, post_id, uploader):
        """Plan B: usa las etiquetas og:video / og:image si no se encontro el JSON."""
        video = self._og_search_video_url(webpage, default=None)
        image = self._og_search_property('image', webpage, default=None)
        media_url = video or image
        if not media_url:
            raise ExtractorError(
                'No se encontro media. El post puede ser privado, solo texto, o Threads cambio su estructura.',
                expected=True)
        return {
            'id': post_id,
            'title': self._og_search_title(webpage, default=f'Threads post {post_id}'),
            'description': self._og_search_description(webpage, default=None),
            'uploader': uploader,
            'url': media_url,
            'ext': 'mp4' if video else 'jpg',
        }
