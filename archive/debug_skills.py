import httpx

r = httpx.get('https://skills.sh/api/search?q=agent', headers={'User-Agent': 'openGuiclaw/1.0'})
skills = r.json().get('skills', [])
if skills:
    s = skills[0]
    print(f"Keys: {list(s.keys())}")
    print(f"Description: {s.get('description')}")
    print(f"Name: {s.get('name')}")
else:
    print("No skills found")
