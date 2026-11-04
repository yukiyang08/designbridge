import routers.favorites as fav


class FakeTable:
    """只模擬 favorites 用到的 upsert / select / delete 鏈，資料存在 rows（以 item_key 為鍵）。"""

    def __init__(self, rows, fail_upsert=False):
        self.rows, self.fail_upsert, self._op, self._keys = rows, fail_upsert, None, None

    def upsert(self, rows, on_conflict=None):
        if self.fail_upsert:
            raise RuntimeError('upsert failed')
        self._op = ('upsert', rows)
        return self

    def select(self, *_):
        self._op = ('select', None)
        return self

    def delete(self):
        self._op = ('delete', None)
        return self

    def eq(self, *_):
        return self

    def in_(self, _col, keys):
        self._keys = keys
        return self

    def execute(self):
        op, payload = self._op
        if op == 'upsert':
            for r in payload:
                self.rows[r['item_key']] = r
        elif op == 'delete':
            for k in self._keys:
                self.rows.pop(k, None)
        data = [{'item_key': k} for k in self.rows] if op == 'select' else None
        return type('R', (), {'data': data})()


def _put(monkeypatch, rows, items, fail_upsert=False):
    table = FakeTable(rows, fail_upsert)
    monkeypatch.setattr(fav, '_get_supabase', lambda: type('SB', (), {'table': lambda self, _n: table})())
    return fav.put_furniture_favorites(fav.FavoritesBody(items=items), user_id='u1')


def test_put_replaces_and_drops_stale(monkeypatch):
    rows = {'A': {'item_key': 'A'}, 'B': {'item_key': 'B'}}
    assert _put(monkeypatch, rows, [{'id': 'B'}, {'id': 'C'}]) == {'count': 2}
    assert set(rows) == {'B', 'C'}


def test_put_empty_clears_all(monkeypatch):
    rows = {'A': {'item_key': 'A'}}
    _put(monkeypatch, rows, [])
    assert rows == {}


def test_failed_write_keeps_old_rows(monkeypatch):
    rows = {'A': {'item_key': 'A'}}
    try:
        _put(monkeypatch, rows, [{'id': 'B'}], fail_upsert=True)
    except RuntimeError:
        pass
    assert set(rows) == {'A'}
