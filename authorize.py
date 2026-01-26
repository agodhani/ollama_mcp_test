#!/usr/bin/env python3
"""
One-time authorization script for Google Calendar.
Run this once to authorize access and generate token.json
"""

import sys
import os

# Add the current directory to path so we can import google_calendar
sys.path.insert(0, os.path.dirname(__file__))

from google_calendar import get_calendar_service

print("Starting Google Calendar authorization flow...")
print("A browser window should open shortly on http://localhost:8000")
print("Please authorize the app and complete the flow.\n")

try:
    service = get_calendar_service()
    print("\n✓ Authorization successful!")
    print("✓ token.json has been created.")
    print("\nYou can now run your client normally.")
except Exception as e:
    print(f"\n✗ Authorization failed: {e}")
    sys.exit(1)
