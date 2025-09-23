import urllib.request
import urllib.parse
import json
from collections import defaultdict
import datetime
import os
import sys

# Konfigurasi
json_url = 'https://weekendsch.pages.dev/sch/schedule.json'
local_json_path = 'schedule.json'  # Path ke file JSON lokal (opsional)
history_file = 'send_history.json'  # File untuk menyimpan riwayat pengiriman

# Ambil dari variabel lingkungan
bot_token = os.environ.get('BOT_TOKEN')
channel_id = os.environ.get('CHANNEL_ID')

# Periksa variabel lingkungan
if not bot_token:
    print("Error: Variabel lingkungan 'BOT_TOKEN' tidak ditemukan.", file=sys.stderr)
    sys.exit(1)
if not channel_id:
    print("Error: Variabel lingkungan 'CHANNEL_ID' tidak ditemukan.", file=sys.stderr)
    sys.exit(1)

allowed_leagues = ['Premier League', 'LaLiga', 'Serie A', 'Champions League', 'england - EFL Cup', 'Bundesliga', 'Europa League']

# Ambil tanggal hari ini (UTC+7)
today = datetime.datetime.now().strftime('%Y-%m-%d')

# Fungsi untuk memeriksa dan memperbarui riwayat pengiriman
def check_and_update_history():
    # Inisialisasi riwayat
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
        except Exception as e:
            print(f"Error membaca file riwayat: {e}", file=sys.stderr)
            return False, history

    # Periksa apakah sudah dikirim untuk tanggal ini
    if today in history:
        print(f"Jadwal untuk {today} sudah dikirim sebelumnya.")
        return True, history  # True berarti sudah dikirim

    return False, history

def save_history(history):
    try:
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=4)
        print(f"Riwayat pengiriman diperbarui untuk {today}")
    except Exception as e:
        print(f"Error menyimpan riwayat: {e}", file=sys.stderr)
        sys.exit(1)

# Periksa riwayat pengiriman
already_sent, history = check_and_update_history()
if already_sent:
    sys.exit(0)  # Keluar jika sudah dikirim

# Fetch data JSON
data = None
try:
    req = urllib.request.Request(json_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"Error fetching JSON: {e}", file=sys.stderr)
    if os.path.exists(local_json_path):
        print("Mencoba membaca dari file JSON lokal...", file=sys.stderr)
        try:
            with open(local_json_path, 'r') as f:
                data = json.load(f)
        except Exception as file_e:
            print(f"Error membaca dari file JSON lokal: {file_e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("File JSON lokal tidak ditemukan. Keluar.", file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f"Error lain saat fetch JSON: {e}", file=sys.stderr)
    sys.exit(1)

# Kelompokkan data untuk hari ini per liga
groups = defaultdict(list)
for match in data:
    if match['kickoff_date'] != today:
        continue
    league = match['league']
    if league not in allowed_leagues:
        continue
    time = match['kickoff_time']
    team1 = match['team1']['name']
    team2 = match['team2']['name']
    match_id = match['id']
    url_match = f"https://gvt720.blogspot.com/?match={match_id}"
    line = f"🕒 {time} | <a href='{url_match}'>{team1} vs {team2}</a>"
    groups[league].append((time, line))

# Jika tidak ada pertandingan hari ini, perbarui riwayat dan keluar
if not groups:
    print("Tidak ada pertandingan untuk hari ini di liga yang dipilih.")
    history[today] = {"sent": True, "timestamp": datetime.datetime.now().isoformat()}
    save_history(history)
    sys.exit(0)

# Bangun pesan
date_obj = datetime.datetime.strptime(today, '%Y-%m-%d')
date_formatted = date_obj.strftime('%B %d, %Y')
msg = f"<b>📢 Match Schedule - {date_formatted} UTC+7</b>\n"
for league in sorted(groups):
    msg += f"\n<b>⚽️ {league}</b>\n"
    sorted_matches = sorted(groups[league])
    for _, line in sorted_matches:
        msg += line + "\n"
msg += "\n<b>govoettv.blogspot.com</b>"

# Kirim ke Telegram channel
telegram_api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
params = {
    'chat_id': channel_id,
    'text': msg,
    'parse_mode': 'HTML'
}
query_string = urllib.parse.urlencode(params)
full_url = telegram_api_url + '?' + query_string
try:
    with urllib.request.urlopen(full_url) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        if result['ok']:
            print(f"Pesan berhasil dikirim untuk tanggal {today}")
            # Perbarui riwayat setelah pengiriman berhasil
            history[today] = {"sent": True, "timestamp": datetime.datetime.now().isoformat()}
            save_history(history)
        else:
            print(f"Gagal mengirim: {result['description']}", file=sys.stderr)
            sys.exit(1)
except Exception as e:
    print(f"Error mengirim pesan: {e}", file=sys.stderr)
    sys.exit(1)
