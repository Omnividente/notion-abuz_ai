import urllib.request
import json
import os

token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
repo = os.environ.get('GITHUB_REPOSITORY') or 'Omnividente/notion-abuz_ai'
# find PR number
