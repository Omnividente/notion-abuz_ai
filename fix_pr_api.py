import os
import json
import urllib.request
import urllib.error

token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
repo = os.environ.get('GITHUB_REPOSITORY') or 'Omnividente/notion-abuz_ai'
pr_number = os.environ.get('PR_NUMBER')

print(f"Token present: {bool(token)}")
print(f"Repo: {repo}")
print(f"PR Number: {pr_number}")
