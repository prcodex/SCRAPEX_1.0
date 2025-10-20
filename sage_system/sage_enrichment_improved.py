#!/usr/bin/env python3
"""
SAGE Improved Enrichment System
- Better HTML text extraction (browser-like)
- Comprehensive error logging
- Detailed diagnostics
"""

import os
import re
import json
import anthropic
from datetime import datetime
from html.parser import HTMLParser
import lancedb
import pandas as pd

# Better HTML stripper that mimics browser rendering
class BrowserLikeHTMLParser(HTMLParser):
    """Extract text from HTML similar to how a browser renders it"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
        self.skip_tags = {'style', 'script', 'head', 'meta', 'link'}
        self.current_tag = None
    
    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.current_tag = tag
        elif tag in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.text.append('\n')
    
    def handle_endtag(self, tag):
        if tag == self.current_tag:
            self.current_tag = None
        elif tag in {'p', 'div', 'li', 'tr'}:
            self.text.append('\n')
    
    def handle_data(self, data):
        if self.current_tag not in self.skip_tags:
            self.text.append(data)
    
    def get_text(self):
        text = ''.join(self.text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        lines = [line.strip() for line in text.split('\n')]
        return '\n'.join(line for line in lines if line)

def extract_text_intelligently(content_text, content_html):
    """Extract text using the best available method"""
    log = []
    
    # Method 1: Use content_text if substantial
    if content_text and len(str(content_text).strip()) > 500:
        text = str(content_text).strip()
        log.append(f"✅ Using content_text: {len(text)} chars")
        return text, log
    
    # Method 2: Parse HTML like a browser
    if content_html and len(str(content_html)) > 1000:
        try:
            parser = BrowserLikeHTMLParser()
            parser.feed(str(content_html))
            text = parser.get_text()
            
            if len(text) > 200:
                log.append(f"✅ Browser-like HTML extraction: {len(text)} chars")
                return text, log
            else:
                log.append(f"⚠️ HTML extraction too short: {len(text)} chars")
        except Exception as e:
            log.append(f"⚠️ HTML parsing failed: {str(e)[:100]}")
    
    # Method 3: Fallback
    text = str(content_text).strip() if content_text else ''
    if text:
        log.append(f"⚠️ Using fallback text: {len(text)} chars")
        return text, log
    
    log.append(f"❌ No usable content found")
    return '', log

def enrich_item(item_id, title, content_text, content_html, sender_name, api_key):
    """Enrich a single item with comprehensive logging"""
    logs = [f"\n{'='*60}", f"📧 {title[:60]}", f"Sender: {sender_name}"]
    
    # Extract text
    text, extraction_logs = extract_text_intelligently(content_text, content_html)
    logs.extend(extraction_logs)
    
    if not text or len(text) < 100:
        logs.append("❌ Insufficient content (<100 chars)")
        return False, None, logs
    
    text_to_analyze = text[:15000]
    logs.append(f"📊 Analyzing {len(text_to_analyze)} chars")
    
    # Determine model
    premium_senders = ['Goldman Sachs', 'Itaú', 'Itau', 'J.P. Morgan', 'Rosenberg Research', 
                       'Bloomberg', 'Financial Times', 'Wall Street Journal']
    use_sonnet = any(s.lower() in sender_name.lower() for s in premium_senders)
    model = "claude-3-5-sonnet-20241022" if use_sonnet else "claude-3-5-haiku-20241022"
    logs.append(f"🤖 Model: {'Sonnet' if use_sonnet else 'Haiku'}")
    
    # Call API
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Detect language
        portuguese_words = ['Brasil', 'mercado', 'economia', 'governo', 'inflação']
        is_portuguese = sum(word in text_to_analyze for word in portuguese_words) > 2
        lang = 'Portuguese' if is_portuguese else 'English'
        logs.append(f"🌐 Language: {lang}")
        
        prompt = f"""Analyze this financial/economic content in {lang}.

{text_to_analyze}

Return ONLY JSON:
{{
  "summary": "3-6 bullet points (• Item 1\\n• Item 2...)",
  "actors": ["people/orgs"],
  "themes": ["topics"],
  "category": "MACRO/ECONOMIC/FX/MARKETS",
  "relevance_score": 7.5
}}"""
        
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        
        ai_text = response.content[0].text.strip()
        logs.append(f"✅ API response: {len(ai_text)} chars")
        
        # Parse JSON
        json_match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            
            # Format summary
            if isinstance(result.get('summary'), list):
                summary = '\n'.join(f"• {s}" for s in result['summary'])
            else:
                summary = result.get('summary', '')
            
            enrichment = {
                'smart_summary': summary,
                'actors': result.get('actors', []),
                'themes': result.get('themes', []),
                'smart_category': result.get('category', 'GENERIC'),
                'ai_relevance_score': float(result.get('relevance_score', 7.0))
            }
            
            logs.append(f"✅ SUCCESS - Summary: {len(summary)} chars, Actors: {len(enrichment['actors'])}, Themes: {len(enrichment['themes'])}")
            return True, enrichment, logs
        else:
            logs.append(f"❌ No JSON in response: {ai_text[:200]}")
            return False, None, logs
            
    except Exception as e:
        logs.append(f"❌ ERROR: {str(e)}")
        return False, None, logs

if __name__ == "__main__":
    print("🚀 SAGE Improved Enrichment")
    print("=" * 80)
    
    # Load API key
    api_key_file = os.path.expanduser('~/.anthropic_key')
    with open(api_key_file, 'r') as f:
        content = f.read().strip()
    match = re.search(r'sk-ant-api03-[A-Za-z0-9_-]+', content)
    api_key = match.group(0)
    
    # Load database
    db = lancedb.connect("s3://sage-unified-feed-lance/sage4/")
    tbl = db.open_table("unified_feed")
    df = tbl.to_pandas()
    
    # Get items needing enrichment
    df['created_at'] = pd.to_datetime(df['created_at'])
    recent = df.sort_values('created_at', ascending=False).head(20)
    
    missing = recent[
        (recent['smart_summary'].isna()) | 
        (recent['smart_summary'].astype(str).str.strip() == '')
    ]
    
    print(f"📊 Found {len(missing)} items needing enrichment\n")
    
    if len(missing) == 0:
        print("✅ All recent emails are enriched!")
        exit(0)
    
    # Process each item
    enriched_count = 0
    
    for idx, row in missing.iterrows():
        success, enrichment, logs = enrich_item(
            item_id=row['id'],
            title=row['title'],
            content_text=row.get('content_text', ''),
            content_html=row.get('content_html', ''),
            sender_name=row.get('display_name', 'Unknown'),
            api_key=api_key
        )
        
        for log_line in logs:
            print(log_line)
        
        if success and enrichment:
            df.loc[idx, 'smart_summary'] = enrichment['smart_summary']
            df.loc[idx, 'actors'] = str(enrichment['actors'])
            df.loc[idx, 'themes'] = str(enrichment['themes'])
            df.loc[idx, 'smart_category'] = enrichment['smart_category']
            df.loc[idx, 'ai_relevance_score'] = enrichment['ai_relevance_score']
            enriched_count += 1
    
    # Save to database
    if enriched_count > 0:
        print(f"\n💾 Updating database with {enriched_count} enrichments...")
        tbl_name = tbl.name
        db.drop_table(tbl_name)
        db.create_table(tbl_name, df)
        print("✅ Database updated!")
    
    print(f"\n{'='*80}")
    print(f"✅ Enriched {enriched_count}/{len(missing)} items")
    print(f"{'='*80}")
