#!/usr/bin/env python3
"""
SAGE Twitter Interface with Authentication
Port 8540 with password protection and cookie-based sessions
"""

from flask import Flask, jsonify, render_template, request, redirect, url_for, session
import lancedb
import pandas as pd
import json
import os
from functools import wraps
from datetime import timedelta

app = Flask(__name__)

# Secret key for sessions (change this to a random string in production)
app.secret_key = 'your-secret-key-change-this-in-production-' + os.urandom(24).hex()

# Session configuration for 30-day cookie
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Password (store this securely - consider using environment variable)
SCRAPEX_PASSWORD = os.environ.get('SCRAPEX_PASSWORD', 'scrapex2025')  # Change this!

# Database connection
db = lancedb.connect("s3://sage-unified-feed-lance/sage4/")
tbl = db.open_table("unified_feed")

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        password = request.form.get('password')
        remember = request.form.get('remember')
        
        if password == SCRAPEX_PASSWORD:
            session['authenticated'] = True
            
            # Make session permanent if remember me is checked
            if remember:
                session.permanent = True
            
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid password. Please try again.')
    
    # If already authenticated, redirect to main page
    if session.get('authenticated'):
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """Main interface - protected by login"""
    return render_template('sage_twitter_enhanced_v2.html')

@app.route('/api/feed')
@login_required
def get_feed():
    """Get feed items - API protected by login"""
    try:
        # Load DataFrame
        df = tbl.to_pandas()
        
        # Sort by date
        df['created_at'] = pd.to_datetime(df['created_at'])
        df = df.sort_values('created_at', ascending=False)
        
        # Get pagination parameters
        offset = int(request.args.get('offset', 0))
        limit = int(request.args.get('limit', 50))
        
        # Paginate
        items_df = df.iloc[offset:offset+limit]
        
        # Load cache and ratings
        cache_file = '/home/ubuntu/newspaper_project/sage_enhanced_cache.json'
        ratings_file = '/home/ubuntu/newspaper_project/sage_ratings.json'
        
        cache = {}
        ratings = {}
        
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                cache = json.load(f)
        
        if os.path.exists(ratings_file):
            with open(ratings_file, 'r') as f:
                ratings = json.load(f)
        
        # Format items
        items = []
        for idx, row in items_df.iterrows():
            item_id = str(row.get('id', ''))
            
            # Get cached data
            cached = cache.get(item_id, {})
            
            # Parse actors and themes from database
            actors = []
            themes = []
            
            if 'actors' in row and pd.notna(row.get('actors')):
                actors_data = row.get('actors')
                if isinstance(actors_data, str):
                    try:
                        import ast
                        actors = ast.literal_eval(actors_data) if actors_data else []
                    except (ValueError, SyntaxError):
                        actors = []
                elif isinstance(actors_data, list):
                    actors = actors_data
            
            if 'themes' in row and pd.notna(row.get('themes')):
                themes_data = row.get('themes')
                if isinstance(themes_data, str):
                    try:
                        import ast
                        themes = ast.literal_eval(themes_data) if themes_data else []
                    except (ValueError, SyntaxError):
                        themes = []
                elif isinstance(themes_data, list):
                    themes = themes_data
            
            item = {
                'id': item_id,
                'title': str(row.get('title', '')),
                'content_text': str(row.get('content_text', '')),
                'content_html': str(row.get('content_html', '')),
                'display_name': str(row.get('display_name', 'Unknown')),
                'created_at': row['created_at'].strftime('%b %d, %I:%M %p'),
                'smart_summary': cached.get('summary') or str(row.get('smart_summary', '')),
                'smart_category': cached.get('category') or str(row.get('smart_category', 'GENERIC')),
                'actors': actors,
                'themes': themes,
                'ai_score': float(row['ai_relevance_score']) if pd.notna(row.get('ai_relevance_score')) else None,
                'user_rating': ratings.get(item_id)
            }
            
            items.append(item)
        
        return jsonify({
            'items': items,
            'has_more': offset + limit < len(df),
            'total': len(df)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/rate', methods=['POST'])
@login_required
def rate_item():
    """Save user rating - protected by login"""
    try:
        data = request.get_json()
        item_id = data.get('item_id')
        rating = data.get('rating')
        
        ratings_file = '/home/ubuntu/newspaper_project/sage_ratings.json'
        
        # Load existing ratings
        ratings = {}
        if os.path.exists(ratings_file):
            with open(ratings_file, 'r') as f:
                ratings = json.load(f)
        
        # Save new rating
        ratings[item_id] = rating
        
        with open(ratings_file, 'w') as f:
            json.dump(ratings, f, indent=2)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8540, debug=False)
