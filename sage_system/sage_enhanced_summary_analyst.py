import anthropic
import re
import os
import json
from html.parser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
        self.skip = False
    
    def handle_starttag(self, tag, attrs):
        if tag.lower() in ['script', 'style']:
            self.skip = True
    
    def handle_endtag(self, tag):
        if tag.lower() in ['script', 'style']:
            self.skip = False
    
    def handle_data(self, d):
        if not self.skip:
            self.text.append(d)
    
    def get_data(self):
        return ''.join(self.text)

def strip_tags(html):
    s = MLStripper()
    try:
        s.feed(html)
        return s.get_data()
    except:
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        return text

def clean_summary(summary):
    if not summary:
        return summary
    
    summary = str(summary) if summary else ''
    
    prefixes = [
        r"Here is a.*?summary.*?:\s*",
        r"Summary:\s*",
    ]
    
    cleaned = summary
    for prefix in prefixes:
        cleaned = re.sub(prefix, "", cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()

def detect_language(text):
    """Detect language - Portuguese vs English"""
    pt_indicators = [
        'ç', 'ã', 'õ', 'á', 'é', 'í', 'ó', 'ú', 'â', 'ê', 'ô',
        ' é ', ' está', ' são ', ' com ', ' para ', ' pela', ' pelo',
        'governo', 'inflação', 'economia', 'brasil', 'copom', 'selic',
        'ipca', 'ibge', 'lula', 'itaú', 'brasileir'
    ]
    
    text_lower = text.lower()
    pt_score = sum(1 for indicator in pt_indicators if indicator in text_lower)
    
    return 'Portuguese' if pt_score >= 2 else 'English'

def identify_content_type(text):
    """Identify detailed content type"""
    combined = text.lower()
    
    categories = {
        'MARKETS': ['s&p', 'nasdaq', 'dow', 'stock', 'shares', 'equity', 'index', 'trading', 'rally', 'sell-off', 'bull', 'bear', 'earnings'],
        'CENTRAL_BANK': ['fed', 'federal reserve', 'ecb', 'boj', 'boe', 'rates', 'monetary policy', 'qe', 'taper', 'hawkish', 'dovish', 'fomc', 'powell'],
        'ECONOMIC': ['gdp', 'inflation', 'cpi', 'pce', 'unemployment', 'jobs', 'payroll', 'recession', 'growth', 'pmi', 'retail sales', 'ipca', 'igp'],
        'FX': ['dollar', 'euro', 'yen', 'pound', 'yuan', 'currency', 'dxy', 'eurusd', 'usdjpy', 'forex', 'exchange rate', 'real', 'brl'],
        'COMMODITIES': ['oil', 'gold', 'silver', 'copper', 'wheat', 'natural gas', 'wti', 'brent', 'opec', 'metals'],
        'POLITICS': ['election', 'president', 'congress', 'senate', 'tariff', 'sanctions', 'geopolitical', 'trade war'],
        'CRYPTO': ['bitcoin', 'ethereum', 'crypto', 'blockchain', 'btc', 'eth'],
        'CORPORATE': ['merger', 'acquisition', 'ipo', 'guidance', 'revenue', 'profit', 'dividend', 'earnings']
    }
    
    scores = {}
    for category, keywords in categories.items():
        score = sum(1 for keyword in keywords if keyword in combined)
        if score > 0:
            scores[category] = score
    
    if scores:
        return max(scores, key=scores.get)
    return 'OTHER'

def map_to_display_category(detailed_type):
    mapping = {
        'ECONOMIC': 'ECONOMIC',
        'MARKETS': 'MACRO',
        'CENTRAL_BANK': 'MACRO',
        'FX': 'MACRO',
        'COMMODITIES': 'MACRO',
        'CORPORATE': 'MACRO',
        'POLITICS': 'POLITICAL',
        'CRYPTO': 'GENERIC',
        'OTHER': 'GENERIC'
    }
    return mapping.get(detailed_type, 'GENERIC')

def should_use_sonnet(detailed_type, sender_name=''):
    """Determine if we should use premium Sonnet model"""
    
    # Premium senders - ALWAYS use Sonnet
    premium_senders = [
        'goldman sachs', 'gs macro', 'gs research', 'gs ',
        'itaú', 'itau', 'itau corretora',
        'j.p. morgan', 'jpmorgan', 'jp morgan',
        'rosenberg', 'rosenberg research',
        'bloomberg', 'financial times', 'ft', 'wall street journal', 'wsj'
    ]
    
    sender_lower = sender_name.lower()
    if any(sender in sender_lower for sender in premium_senders):
        return True
    
    # Premium content types - Use Sonnet
    premium_types = ['ECONOMIC', 'CENTRAL_BANK', 'FX']
    
    if detailed_type in premium_types:
        return True
    
    # Everything else uses Haiku
    return False

def build_adaptive_prompt(text, detailed_type):
    """Build prompt with maximum detail extraction"""
    
    display_category = map_to_display_category(detailed_type)
    language = detect_language(text)
    lang_instruction = "Responda em Português (Brasil)" if language == 'Portuguese' else "Respond in English"
    
    base_prompt = f"""Analyze this {detailed_type.lower()} content and extract MAXIMUM DETAIL.

LANGUAGE: {lang_instruction} - Write your summary in the SAME language as the content.

CRITICAL RULES:
1. Extract ALL numbers, percentages, basis points, levels, prices mentioned
2. Include ALL projections, forecasts, and targets stated
3. Capture ALL comparisons (vs prior, vs expectations, revisions)
4. List ALL names with their titles/roles
5. Include ALL dates, timelines, quarters mentioned
6. ONLY use information EXPLICITLY in the text - NO invention
7. Use 4-7 rich bullet points (• symbol)
8. Each bullet should pack maximum factual detail

"""
    
    if detailed_type in ['MARKETS', 'CENTRAL_BANK', 'ECONOMIC', 'FX', 'COMMODITIES', 'CORPORATE']:
        base_prompt += f"""For {detailed_type} content, make each bullet RICH with:

INCLUDE:
• Specific numbers: percentages, basis points, index levels, prices
• Exact comparisons: "rose from 2.5% to 2.8%", "vs expectations of 2.6%"
• Names with context: "Goldman Sachs Chief Economist Jan Hatzius"
• Dates and timelines: "Q4 2025", "December meeting", "by year-end"
• Forecasts explicitly stated: "projects", "expects", "targets"
• Reasoning given in the text: "citing", "due to", "driven by"

EXAMPLE RICH BULLET (Portuguese):
• Banco Central elevou Selic de 10.75% para 11.25% (+50bp), citando inflação de 4.47% acima do teto da meta de 4.5%, com Copom sinalizando mais um aumento de 50bp em dezembro caso pressões persistam

EXAMPLE RICH BULLET (English):
• Goldman Sachs revised Q4 GDP forecast to 2.8% from 2.5% (vs consensus 2.6%), citing stronger consumer spending (+3.2%) and resilient labor market (unemployment 3.8%)

"""
    else:
        base_prompt += """For non-financial content:
• Briefly describe what this is about (2-3 bullets)
• Stick to facts explicitly stated
• Keep simple and concise

"""
    
    base_prompt += f"""Content:
{text}

Respond in EXACT JSON ({lang_instruction}):
{{
  "summary": "• First rich bullet with ALL numbers/dates/names\\n• Second rich bullet with specifics\\n• Third rich bullet with projections\\n• Fourth bullet if relevant",
  "actors": ["All people/companies/institutions explicitly mentioned"],
  "themes": ["All topics/subjects explicitly discussed"],
  "category": "{display_category}"
}}

Extract MAXIMUM DETAIL from the text. Be FACTUAL - only what's written."""
    
    return base_prompt

def process_sage_item_enhanced(content_text, content_html=None, sender_name=''):
    """
    Process SAGE item with HYBRID Sonnet/Haiku routing
    """
    
    # Load API key from environment or file
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        key_file = os.path.expanduser('~/.anthropic_key')
        if os.path.exists(key_file):
            with open(key_file, 'r') as f:
                for file_line in f:
                    if 'ANTHROPIC_API_KEY' in file_line:
                        api_key = file_line.split('=')[1].strip().strip('"').strip("'")
                        break
    
    if not api_key:
        return {
            'smart_summary': '',
            'actors': [],
            'themes': [],
            'smart_category': 'GENERIC'
        }
    
    text_to_analyze = content_text or ''
    
    if len(text_to_analyze) < 100 and content_html:
        clean_text = strip_tags(content_html)
        text_to_analyze = clean_text
    
    text_to_analyze = ' '.join(text_to_analyze.split())
    text_to_analyze = text_to_analyze[:3000]
    
    if len(text_to_analyze) < 50:
        return {
            'smart_summary': '',
            'actors': [],
            'themes': [],
            'smart_category': 'GENERIC'
        }
    
    try:
        detailed_type = identify_content_type(text_to_analyze)
        prompt = build_adaptive_prompt(text_to_analyze, detailed_type)
        
        # HYBRID ROUTING - Use Sonnet for premium content
        use_sonnet = should_use_sonnet(detailed_type, sender_name)
        
        if use_sonnet:
            model = "claude-3-5-sonnet-20241022"
            print(f"   💎 Using Sonnet for premium content")
        else:
            model = "claude-3-5-haiku-20241022"
            print(f"   ⚡ Using Haiku for standard content")
        
        client = anthropic.Anthropic(api_key=api_key)
        
        try:
            message = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            response_text = message.content[0].text
            
        except Exception as e:
            # Fallback to Haiku if Sonnet fails
            if use_sonnet:
                print(f"   ⚠️ Sonnet failed, falling back to Haiku")
                message = client.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )
                response_text = message.content[0].text
            else:
                raise e
        
        try:
            result = json.loads(response_text)
            
            summary = result.get('summary', '')
            actors = result.get('actors', [])[:5]
            rating = result.get('relevance_score', 7.0)
            themes = result.get('themes', [])[:5]
            category = result.get('category', map_to_display_category(detailed_type))
            
            summary = clean_summary(summary)
            
            return {
                'smart_summary': summary,
                'actors': actors,
                'themes': themes,
                'smart_category': category,
                'ai_relevance_score': float(rating) if rating else 7.0
            }
            
        except json.JSONDecodeError:
            return {
                'smart_summary': '',
                'actors': [],
                'themes': [],
                'smart_category': map_to_display_category(detailed_type)
            }
            
    except Exception as e:
        print(f"Error in AI enrichment: {e}")
        return {
            'smart_summary': '',
            'actors': [],
            'themes': [],
            'smart_category': 'GENERIC'
        }

