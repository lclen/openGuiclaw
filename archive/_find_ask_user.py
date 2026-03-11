content = open('static/js/app-logic.js', encoding='utf-8').read()
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'ask_user' in line or 'ask_user' in line or 'submitAskUser' in line or 'askUser' in line:
        print(f'{i+1}: {line}')
