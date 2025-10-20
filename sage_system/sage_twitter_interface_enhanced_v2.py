#!/usr/bin/env python3
"""
SAGE Twitter Interface - Enhanced with actors and themes
"""

from flask import Flask, render_template, jsonify, request
import lancedb
import json
import ast
import pandas as pd
from datetime import datetime
import pytz
import re
import os

app = Flask(__name__)

# Cache files
SMART_CACHE_FILE = 'sage_smart_cache.json'
ENHANCED_CACHE_FILE = 'sage_enhanced_cache.json'


def clean_summary(summary):
    """Remove common AI prefixes from summaries"""
    if not summary:
        return summary
    
    # List of prefixes to remove
    prefixes = [
        r"Here is a 5-7 line summary of the key points from the text:\s*",
        r"Here is a \d+-\d+ line summary of the content:\s*",
        r"Here is a summary of the content:\s*",
        r"Here is a summary:\s*",
        r"Summary:\s*",
    ]
    
    cleaned = summary
    for prefix in prefixes:
        cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()


def load_smart_cache():
    """Load original smart cache"""
    if os.path.exists(SMART_CACHE_FILE):
        try:
            with open(SMART_CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def load_enhanced_cache():
    """Load enhanced cache with actors and themes"""
    if os.path.exists(ENHANCED_CACHE_FILE):
        try:
            with open(ENHANCED_CACHE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def make_links_clickable(text):
    """Convert URLs, mentions, and hashtags to clickable links"""
    if not text:
        return ""
    
    text = str(text)
    url_pattern = r'(https?://[^\s<>"{}|\^`\[\]]+)'
    text = re.sub(url_pattern, r'<a href="\1" target="_blank" style="color: #1DA1F2;">\1</a>', text)
    mention_pattern = r'@(\w+)'
    text = re.sub(mention_pattern, r'<a href="https://x.com/\1" target="_blank" style="color: #1DA1F2;">@\1</a>', text)
    hashtag_pattern = r'#(\w+)'
    text = re.sub(hashtag_pattern, r'<a href="https://x.com/hashtag/\1" target="_blank" style="color: #1DA1F2;">#\1</a>', text)
    
    return text

def prepare_html_content(html_content):
    """Prepare HTML content for display"""
    if not html_content or not isinstance(html_content, str):
        return ""
    
    styled_html = f"""
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 100%;
            padding: 20px;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 10px 0;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f2f2f2;
        }}
        a {{
            color: #1DA1F2;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
    <div class="email-content">
        {html_content}
    </div>
    """
    
    return styled_html

def get_sage_items():
    """Get SAGE items with enhanced data"""
    try:
        # Connect to LanceDB
        db = lancedb.connect("s3://sage-unified-feed-lance/sage4/")
        table = db.open_table("unified_feed")
        
        # Get all data and sort
        df = table.to_pandas()
        df = df.sort_values('created_at', ascending=False)
        
        # Load caches
        smart_cache = load_smart_cache()
        enhanced_cache = load_enhanced_cache()
        
        # Load user ratings
        user_ratings = {}
        if os.path.exists('sage_ratings.json'):
            with open('sage_ratings.json', 'r') as f:
                user_ratings = json.load(f)
        
        items = []
        
        for idx, row in df.iterrows():
            # Get item ID
            item_id = str(row['id']) if 'id' in row and pd.notna(row['id']) else str(hash(str(row['created_at'])))
            
            # Check caches for enhanced data
            smart_summary = ""
            smart_category = ""
            actors = []
            themes = []
            
            # First check enhanced cache (has everything)
            enhanced_key = f"enhanced_{item_id}"
            if enhanced_key in enhanced_cache:
                cached = enhanced_cache[enhanced_key]
                smart_summary = cached.get('summary', '')
                smart_category = cached.get('category', '')
                actors = cached.get('actors', [])
                themes = cached.get('themes', [])
            # Fall back to original smart cache
            elif f"smart_{item_id}" in smart_cache:
                cached = smart_cache[f"smart_{item_id}"]
                smart_summary = cached.get('summary', '')
                smart_category = cached.get('category', '')
            # CRITICAL: Fall back to database columns if not in cache
            else:
                # Read from database
                if 'smart_summary' in row and pd.notna(row.get('smart_summary')):
                    smart_summary = str(row.get('smart_summary'))
                if 'smart_category' in row and pd.notna(row.get('smart_category')):
                    smart_category = str(row.get('smart_category'))
                if 'actors' in row and pd.notna(row.get('actors')):
                    actors_data = row.get('actors')
                    if isinstance(actors_data, str):
                        try:
                            actors = ast.literal_eval(actors_data) if actors_data else []
                        except:
                            actors = []
                    elif isinstance(actors_data, list):
                        actors = actors_data
                if 'themes' in row and pd.notna(row.get('themes')):
                    themes_data = row.get('themes')
                    if isinstance(themes_data, str):
                        try:
                            themes = ast.literal_eval(themes_data) if themes_data else []
                        except:
                            themes = []
                    elif isinstance(themes_data, list):
                        themes = themes_data
            
            # Initialize display name
            display_name = None
            
            # Get display name
            
            # Initialize display name
            display_name = None
            
            # Check for Itau emails
            if 'content_text' in row and pd.notna(row.get('content_text')):
                content = str(row.get('content_text'))
                if 'Macro Sales Itau' in content or 'ITAU CORRETORA' in content:
                    display_name = 'Itau'
                elif 'Goldman Sachs' in content or '@gs.com' in content:
                    display_name = 'Goldman Sachs'
                elif 'J.P. Morgan' in content or 'JPMorgan' in content:
                    display_name = 'J.P. Morgan'
                elif 'Rosenberg Research' in content:
                    display_name = 'Rosenberg Research'
                elif 'Wall Street Journal' in content or '@wsj.com' in content:
                    display_name = 'Wall Street Journal'
                elif 'Financial Times' in content or '@ft.com' in content:
                    display_name = 'Financial Times'
                elif 'Bloomberg' in content or '@bloomberg' in content:
                    display_name = 'Bloomberg'
                elif 'From: Macro Sales Itau' in content:
                    display_name = 'Itau'
            
            
            # Standard display name detection
            if display_name is None:
                if 'display_name' in row and pd.notna(row.get('display_name')) and str(row.get('display_name')) != 'None':
                    display_name = str(row.get('display_name'))
                elif 'author' in row and pd.notna(row.get('author')) and str(row.get('author')) != 'None':
                    display_name = str(row.get('author'))
                elif 'sender_tag' in row and pd.notna(row.get('sender_tag')) and str(row.get('sender_tag')) != 'None':
                    display_name = str(row.get('sender_tag'))
                else:
                    display_name = 'Unknown'
                display_name = str(row.get('display_name'))
            elif 'author' in row and pd.notna(row.get('author')) and str(row.get('author')) != 'None':
                display_name = str(row.get('author'))
            elif 'sender_tag' in row and pd.notna(row.get('sender_tag')) and str(row.get('sender_tag')) != 'None':
                display_name = str(row.get('sender_tag'))
            else:
                display_name = 'Unknown'
            
            # Clean up common patterns
            display_name = display_name.replace('The Wall Street Journal.', 'Wall Street Journal')
            display_name = display_name.replace('GS ', 'Goldman Sachs ')
            
            # Prepare text content
            content_text = str(row.get('content_text')) if pd.notna(row.get('content_text')) else ''
            
            # Extract only URLs
            import re
            urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', content_text)
            
            # Clean and format URLs
            clean_urls = []
            for url in urls:
                url = url.rstrip('.,;:!?)')
                if 'unsubscribe' not in url.lower() and 'redirect' not in url.lower():
                    if url not in clean_urls:
                        clean_urls.append(url)
            
            # Create clickable links
            if clean_urls:
                html_links = []
                for url in clean_urls[:10]:
                    display = url if len(url) <= 60 else url[:57] + '...'
                    html_links.append(f'<a href="{url}" target="_blank" style="color: #1DA1F2; text-decoration: none;">{display}</a>')
                text = '<br>'.join(html_links)
            else:
                text = ''
            
            # Store full HTML
            full_html = prepare_html_content(row['content_html']) if pd.notna(row['content_html']) and row['content_html'] else None
            
            # Format timestamp
            try:
                created_at = pd.to_datetime(row['created_at'])
                if created_at.tzinfo is None:
                    created_at = created_at.tz_localize('UTC')
                brazil_tz = pytz.timezone('America/Sao_Paulo')
                created_at_brazil = created_at.astimezone(brazil_tz).strftime('%b %d, %I:%M %p')
            except:
                created_at_brazil = str(row['created_at']) if 'created_at' in row else 'Unknown'
            
            # Build item
            item = {
                'id': item_id,
                'text': text,
                'full_html': full_html,
                'full_text': content_text,
                'username': str(row.get('author')) if pd.notna(row.get('author')) else 'Unknown',
                'display_name': display_name,
                'created_at_brazil': created_at_brazil,
                'title': str(row['title']) if pd.notna(row['title']) else '',
                'source_type': str(row['source_type']) if pd.notna(row['source_type']) else 'email',
                'smart_summary': clean_summary(smart_summary),
                'smart_category': smart_category,
                'actors': actors,
                'themes': themes,
                'user_rating': user_ratings.get(item_id, {}).get('rating')
            }
            
            # Add AI enrichment if available
            try:
                item['sentiment'] = str(row['ai_sentiment']) if pd.notna(row['ai_sentiment']) else ''
                item['ai_score'] = float(row['ai_relevance_score']) if pd.notna(row['ai_relevance_score']) else None
                item['ai_keywords'] = json.loads(row['ai_keywords']) if pd.notna(row['ai_keywords']) and row['ai_keywords'] else []
                item['category'] = str(row['ai_category']) if pd.notna(row['ai_category']) else ''
            except:
                pass
            
            # Handle optional fields safely
            item['sender_tag'] = str(row.get('sender_tag', ''))
            item['sender_category'] = str(row.get('sender_category', ''))
            
            items.append(item)
        
        return items
    
    except Exception as e:
        print(f"Error loading SAGE items: {e}")
        import traceback
        traceback.print_exc()
        return []

@app.route('/')
def index():
    """Main interface"""
    items = get_sage_items()
    return render_template('sage_twitter_enhanced_v2.html', initial_items=items[:100])

@app.route('/api/feed')
def api_feed():
    """API endpoint for getting feed items"""
    items = get_sage_items()
    return jsonify({'items': items[:100]})

@app.route('/api/item/<item_id>')
def api_item(item_id):
    """Get single item with full content"""
    items = get_sage_items()
    
    for item in items:
        if item['id'] == item_id:
            return jsonify(item)
    
    return jsonify({'error': 'Item not found'}), 404

@app.route('/api/load_more', methods=['GET'])
def load_more():
    """Load more items"""
    offset = request.args.get('offset', 50, type=int)
    limit = request.args.get('limit', 50, type=int)
    
    items = get_sage_items()
    more_items = items[offset:offset+limit]
    
    return jsonify({
        'items': more_items,
        'has_more': len(items) > (offset + limit),
        'next_offset': offset + limit
    })

@app.route('/api/rate', methods=['POST'])
def rate_item():
    """Save user rating"""
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        rating = data.get('rating')
        
        if not item_id or rating is None:
            return jsonify({'error': 'Missing item_id or rating'}), 400
        
        # Load existing ratings
        ratings_file = 'sage_ratings.json'
        if os.path.exists(ratings_file):
            with open(ratings_file, 'r') as f:
                ratings = json.load(f)
        else:
            ratings = {}
        
        # Update rating
        ratings[item_id] = {
            'rating': rating,
            'timestamp': datetime.now().isoformat()
        }
        
        # Save ratings
        with open(ratings_file, 'w') as f:
            json.dump(ratings, f, indent=2)
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8540, debug=False)
