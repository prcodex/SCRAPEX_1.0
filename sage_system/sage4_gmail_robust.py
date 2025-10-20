#!/usr/bin/env python3
"""
SAGE 4.2 Gmail Fetcher - ROBUST PRODUCTION VERSION
- Bulletproof error handling
- Automatic retry logic
- Connection recovery
- Progress tracking
- Duplicate prevention
- Batch processing for efficiency
"""

import os
import sys
import json
import hashlib
import imaplib
import email
import logging
import traceback
import signal
import time
from datetime import datetime, timedelta
import pandas as pd
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import lancedb
import re
import pytz
import base64

# Setup logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/home/ubuntu/newspaper_project/logs/sage4_gmail_robust.log')
    ]
)
logger = logging.getLogger(__name__)

# Timeout handler
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

class RobustGmailFetcher:
    def __init__(self):
        self.gmail_user = os.getenv('GMAIL_USER', 'prjfiles@gmail.com')
        self.gmail_password = os.getenv('GMAIL_APP_PASSWORD', '')
        
        if not self.gmail_password:
            logger.error("GMAIL_APP_PASSWORD not set! Please source gmail_env.sh")
            sys.exit(1)
        
        # Eastern Time
        self.et = pytz.timezone('America/New_York')
        
        # Connection settings
        self.imap = None
        self.db = None
        self.table = None
        
        # Batch settings
        self.batch_limit = 25  # Safer batch size
        self.max_retries = 3
        self.retry_delay = 5
        
        # Progress tracking
        self.stats = {
            'processed': 0,
            'new': 0,
            'skipped_existing': 0,
            'skipped_blocked': 0,
            'errors': 0
        }
        
        # Initialize connections
        self.connect_to_database()
    
    def connect_to_database(self):
        """Connect to LanceDB with retry logic"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Connecting to LanceDB (attempt {attempt + 1})...")
                self.db = lancedb.connect("s3://sage-unified-feed-lance/sage4/")
                self.table = self.db.open_table("unified_feed")
                logger.info("✅ Database connected successfully")
                return
            except Exception as e:
                logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to database after all retries")
                    sys.exit(1)
    
    def connect_to_gmail(self):
        """Connect to Gmail with retry logic"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Connecting to Gmail (attempt {attempt + 1})...")
                self.imap = imaplib.IMAP4_SSL('imap.gmail.com')
                self.imap.login(self.gmail_user, self.gmail_password)
                self.imap.select('INBOX')
                logger.info("✅ Gmail connected successfully")
                return
            except Exception as e:
                logger.warning(f"Gmail connection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to Gmail after all retries")
                    sys.exit(1)
    
    def safe_disconnect(self):
        """Safely disconnect from Gmail"""
        try:
            if self.imap:
                self.imap.close()
                self.imap.logout()
        except:
            pass
    
    def get_blocked_senders(self):
        """Load blocked senders from file if exists"""
        blocked_file = '/home/ubuntu/newspaper_project/blocked_senders.json'
        try:
            if os.path.exists(blocked_file):
                with open(blocked_file, 'r') as f:
                    data = json.load(f)
                    self.blocked_senders = data.get('blocked_senders', [])
                    self.blocked_emails = data.get('blocked_emails', [])
                    self.blocked_patterns = data.get('blocked_patterns', [])
                    return self.blocked_senders
        except:
            pass
        
        # Default blocked senders (fallback)
        self.blocked_senders = [
            'News Alert (BLOOMBERG)',
            'BI Alert (BLOOMBERG BI ANALYST)'
        ]
        self.blocked_emails = ['noreply@email.com']
        self.blocked_patterns = ['Bloomberg', 'Barron']
        return self.blocked_senders
    
    def is_blocked_sender(self, from_field, sender_name, subject=""):
        """Check if sender is blocked using comprehensive patterns"""
        # Load current blocked configuration
        self.get_blocked_senders()
        
        # Check exact sender name match
        if sender_name in self.blocked_senders:
            return True
        
        # Check email domain patterns
        from_lower = from_field.lower()
        for blocked_email in self.blocked_emails:
            if blocked_email.lower() in from_lower:
                return True
        
        # Check patterns in sender name and subject
        combined_text = f"{sender_name} {subject}".lower()
        for pattern in self.blocked_patterns:
            if pattern.lower() in combined_text:
                return True
        
        # Legacy checks for noreply
        if 'noreply' in from_lower:
            return True
        if 'no-reply' in from_lower:
            return True
        
        return False
    
    def detect_sender_tag(self, from_field, subject, content_text=""):
        """Detect sender organization/tag with enhanced detection"""
        from_lower = from_field.lower()
        subject_lower = subject.lower() if subject else ""
        content_lower = content_text[:1000].lower() if content_text else ""
        
        # Check email domain first
        if '@gs.com' in from_lower or 'goldman sachs' in from_lower:
            return 'Goldman Sachs', 'Investment Bank'
        elif 'itau' in from_lower or '@itau.com' in from_lower or '@itaubba.com' in from_lower:
            return 'Itau', 'Bank'
        elif 'rosenberg' in from_lower or '@rosenbergresearch' in from_lower:
            return 'Rosenberg Research', 'Research'
        elif '@ft.com' in from_lower or 'financial times' in from_lower:
            return 'Financial Times', 'News'
        elif '@wsj.com' in from_lower or 'wall street journal' in from_lower:
            return 'Wall Street Journal', 'News'
        elif '@bloomberg' in from_lower:
            return 'Bloomberg', 'News'
        elif '@jpmorgan.com' in from_lower or 'jp morgan' in from_lower:
            return 'J.P. Morgan', 'Investment Bank'
        elif 'substack' in from_lower:
            return 'Substack', 'Newsletter'
        
        # Check content for Itau if not found in from field
        if 'itau' in content_lower or 'itau corretora' in content_lower:
            return 'Itau', 'Bank'
        
        return None, None
    
    def get_existing_message_ids(self):
        """Get set of existing message IDs from database"""
        existing_ids = set()
        try:
            df = self.table.to_pandas()
            
            for _, row in df[df['source_type'] == 'email'].iterrows():
                custom = row.get('custom_fields', {})
                if isinstance(custom, dict) and 'email' in custom:
                    msg_id = custom['email'].get('message_id')
                    if msg_id:
                        existing_ids.add(msg_id)
            
            logger.info(f"📋 Loaded {len(existing_ids)} existing message IDs")
        except Exception as e:
            logger.warning(f"Could not load existing IDs: {e}")
        
        return existing_ids
    
    def get_last_email_date(self):
        """Get the date of the most recent email in database"""
        try:
            df = self.table.to_pandas()
            emails = df[df['source_type'] == 'email']
            
            if len(emails) == 0:
                # No emails yet, fetch last 24 hours
                return datetime.now(self.et) - timedelta(hours=24)
            
            df['created_at'] = pd.to_datetime(df['created_at'])
            most_recent = emails['created_at'].max()
            
            if hasattr(most_recent, 'to_pydatetime'):
                most_recent = most_recent.to_pydatetime()
            
            # Make timezone-aware
            if most_recent.tzinfo is None:
                most_recent = self.et.localize(most_recent)
            
            logger.info(f"📅 Most recent email: {most_recent.strftime('%Y-%m-%d %I:%M %p ET')}")
            return most_recent
            
        except Exception as e:
            logger.warning(f"Could not get last email date: {e}")
            return datetime.now(self.et) - timedelta(hours=6)
    
    def extract_html_with_images(self, msg):
        """Extract HTML content with embedded images converted to data URLs"""
        try:
            html_content = ""
            plain_content = ""
            embedded_images = {}
            
            # First pass: collect embedded images
            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = str(part.get("Content-Disposition", ""))
                    content_id = part.get("Content-ID", "")
                    
                    if content_id and part.get_content_maintype() == 'image':
                        try:
                            image_data = part.get_payload(decode=True)
                            image_type = part.get_content_subtype()
                            
                            # Create data URL
                            data_url = f"data:image/{image_type};base64,{base64.b64encode(image_data).decode()}"
                            
                            # Store by Content-ID (remove < >)
                            cid = content_id.strip('<>')
                            embedded_images[cid] = data_url
                        except:
                            pass
                
                # Second pass: extract HTML
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))
                    
                    if "attachment" in content_disposition:
                        continue
                    
                    if content_type == "text/html":
                        try:
                            charset = part.get_content_charset() or 'utf-8'
                            html_content = part.get_payload(decode=True).decode(charset, errors='ignore')
                            
                            # Replace CID references with data URLs
                            for cid, data_url in embedded_images.items():
                                html_content = html_content.replace(f'cid:{cid}', data_url)
                            
                            break
                        except:
                            pass
                    elif content_type == "text/plain" and not html_content:
                        try:
                            charset = part.get_content_charset() or 'utf-8'
                            plain_content = part.get_payload(decode=True).decode(charset, errors='ignore')
                        except:
                            pass
            
            # Return HTML if available, otherwise plain text
            if html_content:
                return html_content[:200000]  # Limit size
            elif plain_content:
                return f"<pre>{plain_content[:50000]}</pre>"
            else:
                return "<p>No content available</p>"
                
        except Exception as e:
            logger.warning(f"Error extracting HTML: {e}")
            return "<p>Error extracting content</p>"
    
    def extract_plain_text(self, msg):
        """Extract plain text from email"""
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or 'utf-8'
                        return part.get_payload(decode=True).decode(charset, errors='ignore')[:10000]
            else:
                if msg.get_content_type() == "text/plain":
                    charset = msg.get_content_charset() or 'utf-8'
                    return msg.get_payload(decode=True).decode(charset, errors='ignore')[:10000]
        except:
            pass
        return ""
    
    def process_email(self, msg, msg_id):
        """Process a single email message"""
        try:
            # Extract headers
            subject = str(make_header(decode_header(msg['Subject'] or 'No Subject')))
            from_field = str(make_header(decode_header(msg['From'] or '')))
            date_str = msg['Date']
            
            # Parse sender
            sender_name = from_field.split('<')[0].strip().strip('"')
            sender_email = re.search(r'<(.+?)>', from_field)
            sender_email = sender_email.group(1) if sender_email else from_field
            
            # Check if blocked
            if self.is_blocked_sender(from_field, sender_name, subject):
                self.stats['skipped_blocked'] += 1
                logger.info(f"  🚫 Blocked: {sender_name[:30]} - {subject[:30]}")
                return None
            
            # Parse date
            try:
                email_date = parsedate_to_datetime(date_str)
                # Keep as UTC for consistent storage
                if email_date.tzinfo is None:
                    email_date = pytz.utc.localize(email_date)
                else:
                    # Convert any timezone to UTC
                    email_date = email_date.astimezone(pytz.utc)
            except:
                email_date = datetime.now(pytz.utc)
            
            # Extract content
            html_content = self.extract_html_with_images(msg)
            text_content = self.extract_plain_text(msg)
            
            # Detect sender tag
            sender_tag, sender_category = self.detect_sender_tag(
                from_field, subject, text_content
            )
            
            # Create unique ID
            unique_id = hashlib.md5(f"{msg_id}{email_date}".encode()).hexdigest()
            
            # Build record
            # Store as naive UTC (remove timezone but keep UTC time)
            if hasattr(email_date, 'tzinfo') and email_date.tzinfo is not None:
                email_date_naive = email_date.replace(tzinfo=None)
            else:
                email_date_naive = email_date
            
            record = {
                'id': unique_id,
                'source_type': 'email',
                'source_id': msg_id,
                'created_at': email_date_naive,
                'updated_at': datetime.now(pytz.utc).replace(tzinfo=None),
                'synced_at': datetime.now(pytz.utc).replace(tzinfo=None),
                'author': sender_name,
                'author_email': None,  # Must be None per database schema
                'title': subject[:500],
                'subject': subject[:500],
                'content_text': text_content,
                'content_html': html_content,
                'custom_fields': {
                    'Feed_Type_Flag': 'email',
                    'SenderTag': sender_tag,
                    'email': {
                        'message_id': msg_id,
                        'sender_name': sender_name,
                        'sender_email': sender_email,
                        'has_attachments': False
                    },
                    'media': {
                        'images': [],
                        'links': []
                    },
                    'search_text': f"{sender_name} {subject} {text_content[:500]}"
                }
            }
            
            return record
            
        except Exception as e:
            logger.error(f"Error processing email: {e}")
            self.stats['errors'] += 1
            return None
    
    def fetch_emails(self):
        """Main fetch process with robust error handling"""
        try:
            # Connect to Gmail
            self.connect_to_gmail()
            
            # Get existing IDs
            existing_ids = self.get_existing_message_ids()
            
            # Get last email date
            last_date = self.get_last_email_date()
            search_date = (last_date - timedelta(hours=1)).strftime('%d-%b-%Y')
            
            logger.info(f"🔍 Searching for emails since {search_date}")
            
            # Search for emails
            search_criteria = f'(SINCE {search_date})'
            result, data = self.imap.search(None, search_criteria)
            
            if result != 'OK':
                logger.error(f"Search failed: {result}")
                return
            
            message_ids = data[0].split()
            total_found = len(message_ids)
            
            if total_found == 0:
                logger.info("📭 No new emails found")
                return
            
            logger.info(f"📧 Found {total_found} emails to check")
            
            # Process in reverse order (newest first)
            message_ids = message_ids[::-1]
            
            # Limit to batch size
            to_process = message_ids[:self.batch_limit]
            logger.info(f"⚡ Processing {len(to_process)} emails (batch limit: {self.batch_limit})")
            
            new_emails = []
            
            for idx, msg_id in enumerate(to_process, 1):
                try:
                    # Set timeout for each email
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(30)  # 30 second timeout per email
                    
                    result, msg_data = self.imap.fetch(msg_id, '(RFC822)')
                    
                    if result != 'OK':
                        continue
                    
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Get Message-ID
                    message_id = msg.get('Message-ID', '')
                    if not message_id:
                        message_id = f"no-id-{msg_id.decode()}"
                    
                    # Check if already exists
                    if message_id in existing_ids:
                        self.stats['skipped_existing'] += 1
                        logger.debug(f"  [{idx}/{len(to_process)}] Skipping existing: {message_id[:30]}")
                        continue
                    
                    # Process the email
                    record = self.process_email(msg, message_id)
                    
                    if record:
                        new_emails.append(record)
                        self.stats['new'] += 1
                        logger.info(f"  ✅ [{idx}/{len(to_process)}] NEW: {record['created_at'].strftime('%I:%M %p')} - {record['author'][:30]}")
                    
                    # Cancel timeout
                    signal.alarm(0)
                    
                except TimeoutError:
                    logger.warning(f"  ⏱️ [{idx}] Email processing timed out")
                    self.stats['errors'] += 1
                    signal.alarm(0)
                except Exception as e:
                    logger.error(f"  ❌ [{idx}] Error: {e}")
                    self.stats['errors'] += 1
                    signal.alarm(0)
                
                self.stats['processed'] += 1
            
            # Save to database if we have new emails
            if new_emails:
                logger.info(f"💾 Saving {len(new_emails)} new emails...")
                try:
                    df = pd.DataFrame(new_emails)
                    self.table.add(df)
                    logger.info(f"✅ Successfully saved {len(new_emails)} emails")
                except Exception as e:
                    logger.error(f"Failed to save emails: {e}")
                    # Try saving one by one as fallback
                    saved = 0
                    for email_record in new_emails:
                        try:
                            self.table.add(pd.DataFrame([email_record]))
                            saved += 1
                        except:
                            pass
                    if saved > 0:
                        logger.info(f"✅ Saved {saved}/{len(new_emails)} emails individually")
            
            # Print summary
            logger.info("\n📊 Fetch Summary:")
            logger.info(f"  Total found: {total_found}")
            logger.info(f"  Processed: {self.stats['processed']}")
            logger.info(f"  New: {self.stats['new']}")
            logger.info(f"  Existing: {self.stats['skipped_existing']}")
            logger.info(f"  Blocked: {self.stats['skipped_blocked']}")
            logger.info(f"  Errors: {self.stats['errors']}")
            
            if total_found > self.batch_limit:
                logger.info(f"  📌 {total_found - self.batch_limit} emails remaining for next run")
            
        except Exception as e:
            logger.error(f"Fatal error in fetch process: {e}")
            logger.error(traceback.format_exc())
        finally:
            self.safe_disconnect()

def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("SAGE 4.2 Gmail Fetcher - ROBUST PRODUCTION")
    logger.info("=" * 50)
    
    try:
        fetcher = RobustGmailFetcher()
        fetcher.fetch_emails()
        logger.info("✅ Fetch completed successfully")
        sys.exit(0)
    except KeyboardInterrupt:
        logger.info("⚠️ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()


