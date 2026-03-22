import urllib.request
import urllib.parse
import json
from collections import defaultdict
import datetime
import os
import sys

# ─── Configuration ───────────────────────────────────────────────────────────
JSON_URL = 'https://v2-gvtsch.pages.dev/flashscore.json'
HISTORY_FILE = 'send_history.json'

# Reminder window: send reminder when kickoff is 30-90 min from now
REMINDER_WINDOW_MIN = 30
REMINDER_WINDOW_MAX = 90

# Group matches with kickoff times within this many minutes
GROUP_THRESHOLD = 30

# Telegram credentials from environment
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHANNEL_ID = os.environ.get('CHANNEL_ID')

if not BOT_TOKEN:
    print("Error: 'BOT_TOKEN' environment variable not found.", file=sys.stderr)
    sys.exit(1)
if not CHANNEL_ID:
    print("Error: 'CHANNEL_ID' environment variable not found.", file=sys.stderr)
    sys.exit(1)


# ─── Time Helpers ────────────────────────────────────────────────────────────
# Timezone must be set to Asia/Jakarta (UTC+7) via system or GitHub Actions
now = datetime.datetime.now()
today = now.strftime('%Y-%m-%d')
tomorrow = (now + datetime.timedelta(days=1)).strftime('%Y-%m-%d')


def time_to_minutes(time_str):
    """Convert 'HH:MM' string to minutes since midnight."""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m


def current_minutes():
    """Current time as minutes since midnight."""
    return now.hour * 60 + now.minute


# ─── History Management ─────────────────────────────────────────────────────
def load_history():
    """Load send history from JSON file."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
                print(f"Loaded history with {len(history)} entries: {list(history.keys())}")
                return history
        except Exception:
            print("History file exists but could not be parsed, starting fresh")
            return {}
    print("No history file found, starting fresh")
    return {}


def save_history(history):
    """Save send history to JSON file."""
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving history: {e}", file=sys.stderr)


def clean_old_history(history):
    """Remove history entries older than 7 days."""
    cutoff = (now - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
    return {
        k: v for k, v in history.items()
        if not k.startswith(('overview_', 'reminder_')) or k.split('_')[1] >= cutoff
    }


# ─── Data Fetching ──────────────────────────────────────────────────────────
def fetch_matches():
    """Fetch match data from the JSON endpoint."""
    try:
        req = urllib.request.Request(JSON_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error fetching match data: {e}", file=sys.stderr)
        sys.exit(1)


def get_matches_for_date(data, date_str):
    """Filter matches for a specific date."""
    return [m for m in data if m.get('kickoff_date') == date_str]


# ─── Telegram API ───────────────────────────────────────────────────────────
def send_telegram(text):
    """Send a message to the Telegram channel."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {
        'chat_id': CHANNEL_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true'
    }
    data = urllib.parse.urlencode(params).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('ok'):
                return True
            else:
                print(f"Telegram error: {result.get('description')}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"Error sending message: {e}", file=sys.stderr)
        return False





# ─── Overview Message ───────────────────────────────────────────────────────
def build_overview(matches):
    """Build the full day schedule overview message."""
    if not matches:
        return None

    # Group by league
    groups = defaultdict(list)
    for m in matches:
        groups[m['league']].append(m)

    date_obj = datetime.datetime.strptime(today, '%Y-%m-%d')
    date_formatted = date_obj.strftime('%B %d, %Y')

    msg = f"<b>\U0001F4E2 Match Schedule \u2014 {date_formatted} (UTC+7)</b>\n"

    for league in sorted(groups):
        msg += f"\n<b>\u26BD {league}</b>\n"
        sorted_matches = sorted(groups[league], key=lambda m: m['kickoff_time'])
        for m in sorted_matches:
            team1 = m['team1']['name']
            team2 = m['team2']['name']
            time = m['kickoff_time']
            msg += f"\U0001F552 {time} | {team1} vs {team2}\n"

    msg += f"\n<b>\U0001F4CA Total: {len(matches)} matches today</b>"
    return msg


# ─── Reminder Grouping ──────────────────────────────────────────────────────
def group_matches_by_time(matches):
    """
    Group matches with kickoff times within GROUP_THRESHOLD minutes.
    Returns a list of groups, each group is a list of match dicts.
    """
    if not matches:
        return []

    sorted_matches = sorted(matches, key=lambda m: m['kickoff_time'])
    groups = []
    current_group = [sorted_matches[0]]

    for i in range(1, len(sorted_matches)):
        curr = time_to_minutes(sorted_matches[i]['kickoff_time'])
        group_start = time_to_minutes(current_group[0]['kickoff_time'])

        if curr - group_start <= GROUP_THRESHOLD:
            current_group.append(sorted_matches[i])
        else:
            groups.append(current_group)
            current_group = [sorted_matches[i]]

    groups.append(current_group)
    return groups


def build_reminder(group):
    """
    Build a reminder message for a group of matches.
    - If all matches share the same kickoff time: time in header only
    - If times differ: range in header + time per match line
    """
    times = sorted(set(m['kickoff_time'] for m in group))
    all_same_time = len(times) == 1

    if all_same_time:
        header = f"\U0001F514 Starting in 1 hour! {times[0]} (UTC+7)"
    else:
        header = f"\U0001F514 Starting in 1 hour! {times[0]} - {times[-1]} (UTC+7)"

    msg = f"<b>{header}</b>\n"

    # Sub-group by league
    league_groups = defaultdict(list)
    for m in group:
        league_groups[m['league']].append(m)

    for league in sorted(league_groups):
        msg += f"\n<b>\u26BD {league}</b>\n"
        for m in sorted(league_groups[league], key=lambda x: x['kickoff_time']):
            team1 = m['team1']['name']
            team2 = m['team2']['name']
            if all_same_time:
                msg += f"\u23F0 {team1} vs {team2}\n"
            else:
                msg += f"\u23F0 {m['kickoff_time']} | {team1} vs {team2}\n"

    return msg


def should_send_reminder(group):
    """Check if current time is within the reminder window for this group."""
    earliest_time_str = min(m['kickoff_time'] for m in group)
    # Get the kickoff_date for the match with the earliest time in this group
    earliest_date_str = next(m['kickoff_date'] for m in group if m['kickoff_time'] == earliest_time_str)
    
    # Parse the exact date and time for the earliest match
    try:
        kickoff_dt = datetime.datetime.strptime(f"{earliest_date_str} {earliest_time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return False
        
    diff_minutes = (kickoff_dt - now).total_seconds() / 60
    return REMINDER_WINDOW_MIN <= diff_minutes <= REMINDER_WINDOW_MAX

def get_reminder_key(group):
    """Generate a unique history key for a reminder group."""
    earliest_time_str = min(m['kickoff_time'] for m in group)
    earliest_date_str = next(m['kickoff_date'] for m in group if m['kickoff_time'] == earliest_time_str)
    return f"reminder_{earliest_date_str}_{earliest_time_str}"


# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    history = load_history()
    history = clean_old_history(history)

    # Fetch today's and tomorrow's matches
    data = fetch_matches()
    today_matches = get_matches_for_date(data, today)
    tomorrow_matches = get_matches_for_date(data, tomorrow)

    if not today_matches and not tomorrow_matches:
        print(f"No matches found for {today} and {tomorrow}")
        save_history(history)
        return

    print(f"Found {len(today_matches)} matches for {today}")
    print(f"Found {len(tomorrow_matches)} matches for {tomorrow}")

    # ── Overview (send during midnight hour, 00:00-00:59, history prevents duplicates) ──
    overview_key = f"overview_{today}"
    if now.hour == 0 and overview_key not in history:
        overview_msg = build_overview(today_matches)
        if overview_msg and send_telegram(overview_msg):
            history[overview_key] = now.isoformat()
            print(f"\u2705 Overview sent for {today}")
        else:
            print("\u274C Failed to send overview", file=sys.stderr)

    # ── Reminders (check every run) ──
    # Combine today and tomorrow's matches to catch early morning cross-day mathches
    all_upcoming_matches = today_matches + tomorrow_matches
    
    # We should only group matches that are on the same day. Let's group them first by day, then by time.
    reminder_groups = []
    # group_matches_by_time does not consider date, so we pass days individually
    if today_matches:
        reminder_groups.extend(group_matches_by_time(today_matches))
    if tomorrow_matches:
        reminder_groups.extend(group_matches_by_time(tomorrow_matches))

    for group in reminder_groups:
        rkey = get_reminder_key(group)
        if rkey in history:
            continue
        if should_send_reminder(group):
            reminder_msg = build_reminder(group)
            if send_telegram(reminder_msg):
                history[rkey] = now.isoformat()
                earliest_time = min(m['kickoff_time'] for m in group)
                print(f"\u2705 Reminder sent for matches at {earliest_time}")
            else:
                print("\u274C Failed to send reminder", file=sys.stderr)

    save_history(history)


if __name__ == '__main__':
    main()
