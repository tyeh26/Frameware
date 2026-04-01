import json
import os

from integrations.base import IntegrationBase


class CalendarFetcher(IntegrationBase):
    """
    Google Calendar integration — syncs upcoming events to a local JSON file.

    Expected config.yaml shape:
      integrations:
        calendar:
          enabled: true
          credentials_file: data/calendar/credentials.json
          # token_file: data/calendar/token.json
          # calendar_id: primary
          # lookahead_days: 7
          # output: data/calendar/events.json
          # sync_interval_seconds: 300
    """

    @property
    def sync_interval(self) -> int:
        return int(self.config.get("sync_interval_seconds", 300))

    def fetch_once(self):
        # TODO: implement Google Calendar sync
        # Suggested approach:
        #   1. Authenticate via google-auth / google-api-python-client using OAuth2
        #      credentials stored at self.config["credentials_file"]
        #   2. Call the Calendar API: events().list(calendarId=..., timeMin=now, maxResults=...)
        #   3. Write {"items": ["Event title — HH:MM", ...]} to self.config["output"]
        print("[CalendarFetcher] Not yet implemented.")

    def _placeholder_output(self):
        output = self.config.get("output", "data/calendar/events.json")
        out_path = os.path.join(self.base_dir, output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if not os.path.exists(out_path):
            with open(out_path, "w") as f:
                json.dump({"items": []}, f)
