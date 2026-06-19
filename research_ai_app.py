from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import requests
import pymysql
from sqlalchemy.dialects.mysql import LONGTEXT
pymysql.install_as_MySQLdb()

app = Flask(__name__)
CORS(app)

# ✅ Reads from Railway environment variables
db_url = os.environ.get('DATABASE_URL', '')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'research_ai_secret'

import os
db = SQLAlchemy(app)

# ─────────────────────────────────────────
# GROQ AI CONFIG — reads from Railway env var
# ─────────────────────────────────────────

GROQ_API_KEYS = [k.strip() for k in os.environ.get('GROQ_API_KEY', '').split(',') if k.strip()]
GROQ_URL   = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'llama-3.3-70b-versatile'
MAX_PAPER_CHARS = 28000


def _clip(text):
    if text and len(text) > MAX_PAPER_CHARS:
        return text[:MAX_PAPER_CHARS] + '\n\n[...truncated...]'
    return text or ''


def groq_chat(messages, max_tokens=1024, temperature=0.4):
    for key in GROQ_API_KEYS:
        try:
            resp = requests.post(
                GROQ_URL,
                headers={'Authorization': f'Bearer {key}',
                         'Content-Type': 'application/json'},
                json={
                    'model': GROQ_MODEL,
                    'messages': messages,
                    'temperature': temperature,
                    'max_tokens': max_tokens,
                    'top_p': 0.9,
                    'stream': False,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get('choices', [])
                if choices:
                    return choices[0]['message']['content']
            elif resp.status_code == 429:
                continue
            else:
                continue
        except Exception:
            continue
    return None


# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class User(db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name       = db.Column(db.String(255), nullable=False)
    email      = db.Column(db.String(255), unique=True, nullable=False)
    password   = db.Column(db.String(255), nullable=False)
    interests  = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActiveSession(db.Model):
    __tablename__ = 'active_sessions'
    id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email    = db.Column(db.String(255), nullable=False)
    login_at = db.Column(db.DateTime, default=datetime.utcnow)


class Paper(db.Model):
    __tablename__ = 'papers'
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    file_name   = db.Column(db.String(255), nullable=False)
    title       = db.Column(db.String(500), nullable=False)
    authors     = db.Column(db.String(500), nullable=True)
    year        = db.Column(db.String(10),  nullable=True)
    content     = db.Column(LONGTEXT, nullable=False)
    summary     = db.Column(db.Text, nullable=True)
    citations   = db.Column(db.Text, nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)
    status      = db.Column(db.String(20), default='toRead')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id   = db.Column(db.Integer, db.ForeignKey('papers.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role       = db.Column(db.String(10), nullable=False)
    text       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Note(db.Model):
    __tablename__ = 'notes'
    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    paper_id    = db.Column(db.Integer, db.ForeignKey('papers.id'), nullable=True)
    paper_title = db.Column(db.String(500), nullable=True)
    content     = db.Column(db.Text, nullable=False)
    color       = db.Column(db.String(20), default='#F59E0B')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data     = request.get_json()
        required = ['name', 'email', 'password']
        if not data or not all(k in data for k in required):
            return jsonify({'error': 'Missing required fields'}), 400
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already registered'}), 409
        new_user = User(
            name=data['name'], email=data['email'],
            password=generate_password_hash(data['password']),
            interests=json.dumps(data.get('interests', []))
        )
        db.session.add(new_user)
        db.session.commit()
        session = ActiveSession(email=new_user.email)
        db.session.add(session)
        db.session.commit()
        return jsonify({'message': 'User registered successfully', 'user': {
            'id': new_user.id, 'name': new_user.name, 'email': new_user.email,
            'interests': json.loads(new_user.interests or '[]')
        }}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({'error': 'Email and password required'}), 400
        user = User.query.filter_by(email=data['email']).first()
        if not user or not check_password_hash(user.password, data['password']):
            return jsonify({'error': 'Invalid credentials'}), 401
        session = ActiveSession(email=user.email)
        db.session.add(session)
        db.session.commit()
        return jsonify({'message': 'Login successful', 'user': {
            'id': user.id, 'name': user.name, 'email': user.email,
            'interests': json.loads(user.interests or '[]')
        }}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@app.route('/get_current_user', methods=['GET'])
def get_current_user():
    try:
        last = ActiveSession.query.order_by(ActiveSession.id.desc()).first()
        if not last:
            return jsonify({'error': 'No active user found'}), 404
        user = User.query.filter_by(email=last.email).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({
            'id': user.id, 'name': user.name, 'email': user.email,
            'interests': json.loads(user.interests or '[]')
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/logout', methods=['POST'])
def logout():
    try:
        data  = request.get_json()
        email = data.get('email') if data else None
        if not email:
            return jsonify({'error': 'Email required'}), 400
        ActiveSession.query.filter_by(email=email).delete()
        db.session.commit()
        return jsonify({'message': 'Logged out successfully'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/reset_password', methods=['POST'])
def reset_password():
    try:
        data = request.get_json()
        if not data or 'email' not in data or 'new_password' not in data:
            return jsonify({'error': 'Email and new_password required'}), 400
        user = User.query.filter_by(email=data['email']).first()
        if not user:
            return jsonify({'error': 'No account found for this email'}), 404
        user.password = generate_password_hash(data['new_password'])
        db.session.commit()
        return jsonify({'message': 'Password updated'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────

@app.route('/profile/<int:user_id>', methods=['GET'])
def get_profile(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify({
            'id': user.id, 'name': user.name, 'email': user.email,
            'interests': json.loads(user.interests or '[]'),
            'created_at': user.created_at.strftime('%d %b %Y')
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/profile/<int:user_id>', methods=['PUT'])
def update_profile(user_id):
    try:
        data = request.get_json()
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        user.name = data.get('name', user.name)
        if 'interests' in data:
            user.interests = json.dumps(data['interests'])
        db.session.commit()
        return jsonify({'message': 'Profile updated'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/change_password/<int:user_id>', methods=['PUT'])
def change_password(user_id):
    try:
        data = request.get_json()
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if not check_password_hash(user.password, data.get('current_password', '')):
            return jsonify({'error': 'Current password is incorrect'}), 401
        user.password = generate_password_hash(data['new_password'])
        db.session.commit()
        return jsonify({'message': 'Password changed'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# PAPERS + AI ANALYSIS
# ─────────────────────────────────────────

@app.route('/papers/<int:user_id>', methods=['GET'])
def get_papers(user_id):
    try:
        favorite = request.args.get('favorite')
        status   = request.args.get('status')
        query    = Paper.query.filter_by(user_id=user_id)
        if favorite == 'true':
            query = query.filter_by(is_favorite=True)
        if status:
            query = query.filter_by(status=status)
        papers = query.order_by(Paper.created_at.desc()).all()
        return jsonify([{
            'id': p.id, 'file_name': p.file_name, 'title': p.title,
            'authors': p.authors, 'year': p.year, 'summary': p.summary,
            'is_favorite': p.is_favorite, 'status': p.status,
            'created_at': p.created_at.strftime('%d %b %Y')
        } for p in papers]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/papers/detail/<int:paper_id>', methods=['GET'])
def get_paper_detail(paper_id):
    try:
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        return jsonify({
            'id': p.id, 'file_name': p.file_name, 'title': p.title,
            'authors': p.authors, 'year': p.year, 'content': p.content,
            'summary': p.summary, 'citations': p.citations,
            'is_favorite': p.is_favorite, 'status': p.status,
            'created_at': p.created_at.strftime('%d %b %Y')
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/papers/analyze', methods=['POST'])
def analyze_paper():
    try:
        data     = request.get_json()
        required = ['user_id', 'file_name', 'content']
        if not data or not all(k in data for k in required):
            return jsonify({'error': 'Missing required fields'}), 400
        content = data['content']
        meta_raw = groq_chat([
            {'role': 'system', 'content': 'You extract bibliographic metadata. Reply ONLY with raw JSON, no markdown.'},
            {'role': 'user', 'content': 'From this paper return JSON: {"title":"...","authors":"First-author et al.","year":"YYYY"}. If unknown use "".\n\n' + _clip(content)},
        ], max_tokens=200, temperature=0.0)
        title, authors, year = '', '', ''
        if meta_raw:
            try:
                clean   = meta_raw.replace('```json', '').replace('```', '').strip()
                m       = json.loads(clean)
                title   = m.get('title', '') or ''
                authors = m.get('authors', '') or ''
                year    = m.get('year', '') or ''
            except Exception:
                pass
        if not title:
            title = data['file_name'].rsplit('.', 1)[0]
        summary = groq_chat([
            {'role': 'system', 'content': 'You are ResearchAI. Explain papers in simple, clear language with no jargon.'},
            {'role': 'user', 'content': "Summarize this paper in SIMPLE language with short sections: What it's about, Methods, Key findings, Why it matters, Limitations.\n\n" + _clip(content)},
        ], max_tokens=1500)
        if summary is None:
            return jsonify({'error': 'AI is busy right now. Please try again.'}), 503
        paper = Paper(
            user_id=data['user_id'], file_name=data['file_name'],
            title=title, authors=authors, year=year,
            content=content, summary=summary,
        )
        db.session.add(paper)
        db.session.commit()
        return jsonify({'message': 'Paper analyzed', 'paper': {
            'id': paper.id, 'file_name': paper.file_name, 'title': paper.title,
            'authors': paper.authors, 'year': paper.year, 'summary': paper.summary,
            'is_favorite': paper.is_favorite, 'status': paper.status
        }}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/citations', methods=['GET'])
def paper_citations(paper_id):
    try:
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        if p.citations:
            return jsonify({'citations': p.citations}), 200
        result = groq_chat([
            {'role': 'system', 'content': 'You produce accurate IEEE-style reference lists.'},
            {'role': 'user', 'content': 'Find the reference/bibliography entries and reformat them in IEEE style, numbered [1], [2], [3]. If none are found, write "No reference list detected." then suggest 3-5 relevant works under "Suggested related references (AI-generated, verify):". Output only the list.\n\n' + _clip(p.content)},
        ], max_tokens=1800)
        if result is None:
            return jsonify({'error': 'AI is busy right now. Please try again.'}), 503
        p.citations = result
        db.session.commit()
        return jsonify({'citations': result}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/cite', methods=['POST'])
def cite_paper(paper_id):
    try:
        data  = request.get_json()
        style = data.get('style', 'IEEE') if data else 'IEEE'
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        result = groq_chat([
            {'role': 'system', 'content': f'You generate one accurate {style} citation for the paper.'},
            {'role': 'user', 'content': f'Generate a single {style}-style citation for THIS paper (the document itself, not its references). Output only the citation text.\n\n' + _clip(p.content)},
        ], max_tokens=400, temperature=0.1)
        if result is None:
            return jsonify({'error': 'AI is busy right now. Please try again.'}), 503
        return jsonify({'style': style, 'citation': result.strip()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/favorite', methods=['POST'])
def toggle_favorite(paper_id):
    try:
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        p.is_favorite = not p.is_favorite
        db.session.commit()
        return jsonify({'message': 'Updated', 'is_favorite': p.is_favorite}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/status', methods=['PUT'])
def set_status(paper_id):
    try:
        data   = request.get_json()
        status = data.get('status')
        if status not in ('toRead', 'reading', 'completed'):
            return jsonify({'error': 'Invalid status'}), 400
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        p.status = status
        db.session.commit()
        return jsonify({'message': 'Status updated'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>', methods=['DELETE'])
def delete_paper(paper_id):
    try:
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        ChatMessage.query.filter_by(paper_id=paper_id).delete()
        db.session.delete(p)
        db.session.commit()
        return jsonify({'message': 'Paper deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# CHAT WITH PAPER
# ─────────────────────────────────────────

@app.route('/papers/<int:paper_id>/chat', methods=['GET'])
def get_chat(paper_id):
    try:
        msgs = ChatMessage.query.filter_by(paper_id=paper_id)\
            .order_by(ChatMessage.created_at.asc()).all()
        return jsonify([{
            'id': m.id, 'role': m.role, 'text': m.text,
            'created_at': m.created_at.strftime('%d %b %Y %H:%M')
        } for m in msgs]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/chat', methods=['POST'])
def ask_paper(paper_id):
    try:
        data     = request.get_json()
        question = (data.get('question') or '').strip() if data else ''
        user_id  = data.get('user_id')
        if not question:
            return jsonify({'error': 'Question required'}), 400
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        db.session.add(ChatMessage(paper_id=paper_id, user_id=user_id,
                                   role='user', text=question))
        db.session.commit()
        history = ChatMessage.query.filter_by(paper_id=paper_id)\
            .order_by(ChatMessage.created_at.desc()).limit(8).all()
        history = list(reversed(history))
        messages = [{'role': 'system',
                     'content': 'You are ResearchAI. Answer ONLY from the paper below. If the answer is not in it, say so and mark general info as "(general knowledge)".\n\n=== PAPER ===\n' + _clip(p.content) + '\n=== END ==='}]
        for m in history:
            messages.append({'role': 'user' if m.role == 'user' else 'assistant',
                             'content': m.text})
        answer = groq_chat(messages, max_tokens=1024)
        if answer is None:
            return jsonify({'error': 'AI is busy right now. Please try again.'}), 503
        db.session.add(ChatMessage(paper_id=paper_id, user_id=user_id,
                                   role='ai', text=answer))
        db.session.commit()
        return jsonify({'answer': answer}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# NOTES
# ─────────────────────────────────────────

@app.route('/notes/<int:user_id>', methods=['GET'])
def get_notes(user_id):
    try:
        notes = Note.query.filter_by(user_id=user_id)\
            .order_by(Note.created_at.desc()).all()
        return jsonify([{
            'id': n.id, 'content': n.content, 'paper_title': n.paper_title,
            'color': n.color, 'created_at': n.created_at.strftime('%d %b %Y')
        } for n in notes]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/notes', methods=['POST'])
def add_note():
    try:
        data     = request.get_json()
        required = ['user_id', 'content']
        if not data or not all(k in data for k in required):
            return jsonify({'error': 'Missing required fields'}), 400
        note = Note(
            user_id=data['user_id'], content=data['content'],
            paper_id=data.get('paper_id'),
            paper_title=data.get('paper_title', ''),
            color=data.get('color', '#F59E0B')
        )
        db.session.add(note)
        db.session.commit()
        return jsonify({'message': 'Note added', 'id': note.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/notes/<int:note_id>', methods=['DELETE'])
def delete_note(note_id):
    try:
        note = Note.query.get(note_id)
        if not note:
            return jsonify({'error': 'Note not found'}), 404
        db.session.delete(note)
        db.session.commit()
        return jsonify({'message': 'Note deleted'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ─────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────

@app.route('/dashboard/<int:user_id>', methods=['GET'])
def get_dashboard(user_id):
    try:
        all_papers  = Paper.query.filter_by(user_id=user_id).all()
        recent      = Paper.query.filter_by(user_id=user_id)\
            .order_by(Paper.created_at.desc()).limit(4).all()
        notes_count = Note.query.filter_by(user_id=user_id).count()
        return jsonify({
            'total_papers': len(all_papers),
            'favorites':  sum(1 for p in all_papers if p.is_favorite),
            'reading':    sum(1 for p in all_papers if p.status == 'reading'),
            'completed':  sum(1 for p in all_papers if p.status == 'completed'),
            'notes': notes_count,
            'recent_papers': [{
                'id': p.id, 'title': p.title, 'authors': p.authors,
                'year': p.year, 'status': p.status, 'is_favorite': p.is_favorite
            } for p in recent]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
