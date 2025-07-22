import requests
import json
import argparse
import sys

# --- Configuration ---
# The Warcraft Logs API endpoints.
TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"

# --- Functions for WCL API Interaction ---

def get_access_token(client_id, client_secret):
    """Authenticates with the WCL API to get an access token."""
    print("Requesting access token...")
    try:
        data = {"grant_type": "client_credentials"}
        auth = (client_id, client_secret)
        response = requests.post(TOKEN_URL, data=data, auth=auth)
        response.raise_for_status()
        token_data = response.json()
        print("Access token received successfully.")
        return token_data.get("access_token")
    except requests.exceptions.RequestException as e:
        print(f"Error getting access token: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response.status_code == 401:
            print("Authentication failed (401 Unauthorized). Please check your Client ID and Client Secret.", file=sys.stderr)
        return None

def get_fight_details(report_id, token, fight_id_str="last"):
    """
    Fetches master data and details for a specific fight.
    Returns the fight ID, the dungeon ID (zone.id), and a list of all NPC actors in the report.
    """
    print(f"Fetching master data and fight details for report: {report_id}...")
    # Corrected Query: Fetches masterData for all NPCs in the report.
    query = """
    query($report_id: String!) {
      reportData {
        report(code: $report_id) {
          zone {
            id
          }
          masterData {
            actors(type: "NPC") {
              id
              name
              gameID 
            }
          }
          fights {
            id
            name
            startTime
            keystoneLevel
          }
        }
      }
    }
    """
    variables = {"report_id": report_id}
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            print(f"GraphQL API Error: {data['errors']}", file=sys.stderr)
            return None, None, None
        
        report_data = data.get("data", {}).get("reportData", {}).get("report", {})
        if not report_data:
            print("Could not find report data.", file=sys.stderr)
            return None, None, None

        fights = report_data.get("fights", [])
        if not fights:
            print("No fights found in this report.", file=sys.stderr)
            return None, None, None

        target_fight = None
        if fight_id_str == "last":
            mplus_fights = [f for f in fights if f.get('keystoneLevel') is not None]
            if mplus_fights:
                target_fight = mplus_fights[-1]
            else: 
                target_fight = fights[-1]
            print(f"Found last relevant fight: '{target_fight['name']}' (ID: {target_fight['id']})")
        else:
            try:
                fight_id_num = int(fight_id_str)
                target_fight = next((f for f in fights if f['id'] == fight_id_num), None)
                if not target_fight:
                    print(f"Fight ID '{fight_id_num}' not found in the report.", file=sys.stderr)
                    return None, None, None
                print(f"Found specified fight: '{target_fight['name']}' (ID: {target_fight['id']})")
            except ValueError:
                print(f"Invalid fight ID '{fight_id_str}'. Must be 'last' or a number.", file=sys.stderr)
                return None, None, None
        
        zone_data = report_data.get("zone", {})
        dungeon_id = zone_data.get("id")
        if not dungeon_id:
             print(f"Warning: Could not determine Dungeon ID from report's zone information.", file=sys.stderr)

        npc_actors = report_data.get("masterData", {}).get("actors", [])
        if not npc_actors:
            print("Warning: Could not fetch NPC master data from the report.", file=sys.stderr)

        return target_fight['id'], dungeon_id, npc_actors

    except requests.exceptions.RequestException as e:
        print(f"Error fetching fights: {e}", file=sys.stderr)
        return None, None, None


def get_fight_events(report_id, fight_id, token):
    """Retrieves all events for a specific fight within a report."""
    print(f"Fetching all events for fight ID: {fight_id}...")
    query = """
    query($report_id: String!, $fight_id: [Int!]!, $startTime: Float) {
      reportData {
        report(code: $report_id) {
          events(fightIDs: $fight_id, startTime: $startTime, limit: 10000, dataType: All) {
            data
            nextPageTimestamp
          }
        }
      }
    }
    """
    variables = {"report_id": report_id, "fight_id": [fight_id]}
    headers = {"Authorization": f"Bearer {token}"}
    all_events = []
    next_page_timestamp = 0

    while True:
        variables['startTime'] = next_page_timestamp
        
        try:
            response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                print(f"GraphQL API Error: {data['errors']}", file=sys.stderr)
                return None

            report_events = data.get("data", {}).get("reportData", {}).get("report", {}).get("events", {})
            events_data = report_events.get("data", [])
            all_events.extend(events_data)
            
            next_page_timestamp = report_events.get('nextPageTimestamp')
            if not next_page_timestamp:
                break
            
            print(f"  ...fetched {len(events_data)} events, getting next page...")

        except requests.exceptions.RequestException as e:
            print(f"Error fetching events: {e}", file=sys.stderr)
            return None

    print(f"Successfully retrieved a total of {len(all_events)} events.")
    return all_events

# --- Functions for MDT Conversion ---

def process_events_for_mdt(events, npc_master_data, pull_reset_timer_ms=10000):
    """
    Processes raw WCL events to identify pulls and the NPCs within them.
    A new pull is started if there's a gap in combat longer than the timer.
    """
    print("Processing events to identify pulls...")
    
    # Build a lookup dictionary from the masterData actors list.
    # Key: sourceID from events, Value: {name, npcID}
    combatant_info = {
        actor['id']: {'name': actor['name'], 'npcID': actor.get('gameID')}
        for actor in npc_master_data if actor.get('gameID') is not None
    }

    if not combatant_info:
        print("Error: No valid NPC actor data found. Cannot process pulls.", file=sys.stderr)
        return []

    pulls = []
    current_pull_instance_ids = set()
    last_event_timestamp = 0

    # Filter for damage events against known enemy NPCs and sort by time
    # Also consider 'cast' events to catch pulls that might not start with damage (e.g., patrols)
    combat_events = sorted(
        [e for e in events if (e['type'] == 'damage' and e.get('targetID') in combatant_info) or \
                               (e['type'] == 'cast' and e.get('sourceID') in combatant_info)],
        key=lambda x: x['timestamp']
    )

    if not combat_events:
        print("No relevant combat events found for enemy NPCs. Cannot determine pulls.", file=sys.stderr)
        return []

    last_event_timestamp = combat_events[0]['timestamp']

    for event in combat_events:
        timestamp = event['timestamp']
        
        actor_id = event.get('targetID') if event['type'] == 'damage' else event.get('sourceID')
        if actor_id not in combatant_info:
            continue

        if current_pull_instance_ids and (timestamp - last_event_timestamp > pull_reset_timer_ms):
            pulls.append(list(current_pull_instance_ids))
            print(f"  - New pull identified after {(timestamp - last_event_timestamp)/1000:.1f}s of inactivity. Pull #{len(pulls)} has {len(current_pull_instance_ids)} mobs.")
            current_pull_instance_ids = set()

        current_pull_instance_ids.add(actor_id)
        last_event_timestamp = timestamp

    # Add the final pull to the list
    if current_pull_instance_ids:
        pulls.append(list(current_pull_instance_ids))
        print(f"  - Final pull identified. Pull #{len(pulls)} has {len(current_pull_instance_ids)} mobs.")

    # Map instance IDs back to the base NPC ID for MDT.
    mapped_pulls = []
    for pull_instance_ids in pulls:
        mapped_pull = {
            combatant_info[inst_id]['npcID'] 
            for inst_id in pull_instance_ids 
            if inst_id in combatant_info and combatant_info[inst_id].get('npcID')
        }
        if mapped_pull: 
            mapped_pulls.append(list(mapped_pull))
    
    print(f"Finished processing. Found {len(mapped_pulls)} distinct pulls.")
    return mapped_pulls


def generate_mdt_lua_string(pulls, dungeon_id):
    """Generates the final MDT importable string from the list of pulls."""
    print("Generating MDT Lua string...")
    
    pull_strings = []
    for i, pull_npcs in enumerate(pulls):
        npc_strings = []
        for npc_id in pull_npcs:
            npc_strings.append(f"{{[\"id\"]={npc_id}}}")
        
        pull_strings.append(f"[{i+1}]={{[\"npcs\"]={{ {','.join(npc_strings)} }} }}")

    lua_string = f"""!nN11VTTXv4NMetKqLhMLGvHPLRkQk2KzL58GGFKqVqS0rqeVt6S05sYhXhQ3qUqVqUqDqUq1UqVSD5Wl(qVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqVqV-{{
  ["pulls"] = {{ {",".join(pull_strings)} }},
  ["dungeon"] = {dungeon_id or 0},
  ["week"] = 1,
  ["version"] = 2,
  ["name"] = "Imported from WCL"
}}
"""
    return lua_string.replace('\n', '')


def main():
    """Main function to run the log retrieval and conversion process."""
    parser = argparse.ArgumentParser(description="Convert Warcraft Logs report pulls to a Mythic Dungeon Tool import string.")
    parser.add_argument("--client-id", required=True, help="Your Warcraft Logs API v2 Client ID.")
    parser.add_argument("--client-secret", required=True, help="Your Warcraft Logs API v2 Client Secret.")
    parser.add_argument("--url", required=True, help="Full URL of the WCL report (e.g., https://www.warcraftlogs.com/reports/someID).")
    parser.add_argument("--fight", default="last", help="The fight ID to analyze. Use 'last' for the last fight in the report or a specific number. (default: last)")
    
    args = parser.parse_args()

    try:
        report_id = args.url.split('/reports/')[-1].split('?')[0].split('#')[0]
        if len(report_id) != 16:
             raise ValueError("Invalid Report ID format.")
    except (IndexError, ValueError):
        print("Invalid URL format. Please use a URL like 'https://www.warcraftlogs.com/reports/someReportID'.", file=sys.stderr)
        return

    token = get_access_token(args.client_id, args.client_secret)
    if not token:
        return

    fight_id, dungeon_id, npc_master_data = get_fight_details(report_id, token, args.fight)
    if not fight_id:
        return

    events = get_fight_events(report_id, fight_id, token)
    if not events:
        return

    pulls = process_events_for_mdt(events, npc_master_data)
    if not pulls:
        print("Could not identify any pulls from the log data.", file=sys.stderr)
        return
        
    mdt_string = generate_mdt_lua_string(pulls, dungeon_id)

    filename = f"mdt_import_{report_id}_fight_{fight_id}.txt"
    with open(filename, "w") as f:
        f.write(mdt_string)
        
    print("\n" + "="*50)
    print("MDT IMPORT STRING GENERATED SUCCESSFULLY")
    print("="*50)
    print(f"\nThe import string has been saved to: {filename}")
    print("\nCOPY THE ENTIRE STRING BELOW AND IMPORT IT INTO MYTHIC DUNGEON TOOL:\n")
    print(mdt_string)
    print("\n" + "="*50)


if __name__ == "__main__":
    main()

