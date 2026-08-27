import httpx, sys
sys.path.insert(0, '.')
api_key = 'jca_6q6jLup89o7vSnkTb2PLfjLdo36ArrVKdLq9'
headers = {'x-api-key': api_key, 'Accept': 'application/json'}
sid = '69b2b23424aa13629a2bfe06'
r = httpx.get('https://console.jumpcloud.com/api/v2/systeminsights/apps',
    headers=headers, params={'limit': 100, 'filter': 'system_id:eq:' + sid}, timeout=20)
print('status:', r.status_code, 'count:', len(r.json()) if isinstance(r.json(), list) else 'error')
data = r.json()
if not isinstance(data, list):
    print(data)
    exit()
print('Total apps:', len(data))
for a in data:
    display = (a.get('display_name') or '').lower()
    name = (a.get('bundle_name') or '').lower()
    bid = (a.get('bundle_identifier') or '').lower()
    if 'chrome' in display or 'chrome' in name or 'chrome' in bid:
        print(f"bundle_id={bid} | display={a.get('display_name')} | name={a.get('bundle_name')} | version={a.get('bundle_short_version')}")
