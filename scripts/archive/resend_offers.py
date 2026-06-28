import sys, os, requests, json, glob
sys.path.insert(0, 'scripts')

BOT_TOKEN = os.getenv('TELEGRAM_TOKEN')
OWNER_ID = 335699027

files = sorted(glob.glob('data/offers/*.json'), key=os.path.getmtime, reverse=True)[:15]
sent = 0

for fpath in files:
    with open(fpath) as f:
        offer = json.load(f)

    if offer.get('status') in ['RESPONDED', 'HIDDEN', 'SCAM']:
        continue
    if sent >= 5:
        break

    oid = offer['offer_id']
    d = offer['display']
    raw = offer['raw']

    username = raw.get('sender_username')
    sender_name = (d.get('sender_name') or 'Аноним').replace('_', ' ')
    if username:
        contact = "https://t.me/" + username
    elif raw.get('sender_id'):
        contact = "tg://user?id=" + str(raw['sender_id'])
    else:
        contact = sender_name

    preview = (d.get('preview') or '')[:250]
    preview = preview.replace('*','').replace('[','').replace(']','').replace('`','').replace('_',' ')
    kw = ', '.join(d.get('keywords', [])[:3])
    chat = d.get('chat_name', '')

    text = "Оффер: " + oid + "\nКанал: " + chat + "\nКонтакт: " + contact + "\nКлючевые: " + kw + "\n\n" + preview

    kb = {'inline_keyboard': [[
        {'text': 'Откликнуться', 'callback_data': 'respond:' + oid},
        {'text': 'Скам', 'callback_data': 'scam:' + oid},
    ],[
        {'text': 'Скрыть', 'callback_data': 'hide:' + oid},
        {'text': 'Делегировать', 'callback_data': 'delegate:' + oid},
    ]]}

    r = requests.post(
        'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage',
        json={
            'chat_id': OWNER_ID,
            'text': text,
            'disable_web_page_preview': True,
            'reply_markup': kb,
        }
    )
    print(oid + ': ' + str(r.status_code))
    if r.status_code != 200:
        print(r.text[:200])
    sent += 1
