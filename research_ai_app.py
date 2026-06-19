from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import json
import pymysql
from sqlalchemy.dialects.mysql import LONGTEXT
pymysql.install_as_MySQLdb()

app = Flask(__name__)
CORS(app)

# Reads the DB URL from Railway env. Set DATABASE_URL in Railway > Variables to
# your MySQL connection string, e.g. mysql://user:pass@host:port/dbname
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', '')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'research_ai_secret'

db = SQLAlchemy(app)


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
    role       = db.Column(db.String(10), nullable=False)   # 'user' | 'ai'
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
        data = request.get_json()
        if not data or not all(k in data for k in ['name', 'email', 'password']):
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
        db.session.add(ActiveSession(email=new_user.email))
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
        db.session.add(ActiveSession(email=user.email))
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
        data = request.get_json()
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
# PAPERS  (storage only — AI happens in the Flutter app)
# ─────────────────────────────────────────

@app.route('/papers/<int:user_id>', methods=['GET'])
def get_papers(user_id):
    try:
        favorite = request.args.get('favorite')
        status   = request.args.get('status')
        query = Paper.query.filter_by(user_id=user_id)
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


@app.route('/papers', methods=['POST'])
def save_paper():
    """The Flutter app already extracted text and made the summary with Groq.
    This just stores everything."""
    try:
        data = request.get_json()
        required = ['user_id', 'file_name', 'title', 'content']
        if not data or not all(k in data for k in required):
            return jsonify({'error': 'Missing required fields'}), 400
        paper = Paper(
            user_id=data['user_id'], file_name=data['file_name'],
            title=data['title'], authors=data.get('authors', ''),
            year=data.get('year', ''), content=data['content'],
            summary=data.get('summary', ''),
        )
        db.session.add(paper)
        db.session.commit()
        return jsonify({'message': 'Paper saved', 'paper': {
            'id': paper.id, 'file_name': paper.file_name, 'title': paper.title,
            'authors': paper.authors, 'year': paper.year, 'summary': paper.summary,
            'is_favorite': paper.is_favorite, 'status': paper.status
        }}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/citations', methods=['PUT'])
def save_citations(paper_id):
    """Store the IEEE citations the app generated, so they load instantly next time."""
    try:
        data = request.get_json()
        p = Paper.query.get(paper_id)
        if not p:
            return jsonify({'error': 'Paper not found'}), 404
        p.citations = data.get('citations', '')
        db.session.commit()
        return jsonify({'message': 'Citations saved'}), 200
    except Exception as e:
        db.session.rollback()
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
        data = request.get_json()
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
# CHAT (history storage only — answers come from Groq in the app)
# ─────────────────────────────────────────

@app.route('/papers/<int:paper_id>/chat', methods=['GET'])
def get_chat(paper_id):
    try:
        msgs = ChatMessage.query.filter_by(paper_id=paper_id)\
            .order_by(ChatMessage.created_at.asc()).all()
        return jsonify([{
            'id': m.id, 'role': m.role, 'text': m.text
        } for m in msgs]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/papers/<int:paper_id>/chat', methods=['POST'])
def save_chat(paper_id):
    """Save one message. The app posts the user's question and the AI answer."""
    try:
        data = request.get_json()
        role = data.get('role')
        text = (data.get('text') or '').strip()
        user_id = data.get('user_id')
        if role not in ('user', 'ai') or not text:
            return jsonify({'error': 'role (user|ai) and text required'}), 400
        db.session.add(ChatMessage(paper_id=paper_id, user_id=user_id,
                                   role=role, text=text))
        db.session.commit()
        return jsonify({'message': 'Saved'}), 201
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
            'color': n.color
        } for n in notes]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/notes', methods=['POST'])
def add_note():
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['user_id', 'content']):
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
# HOME DASHBOARD
# ─────────────────────────────────────────

@app.route('/dashboard/<int:user_id>', methods=['GET'])
def get_dashboard(user_id):
    try:
        all_papers = Paper.query.filter_by(user_id=user_id).all()
        recent = Paper.query.filter_by(user_id=user_id)\
            .order_by(Paper.created_at.desc()).limit(4).all()
        notes_count = Note.query.filter_by(user_id=user_id).count()
        return jsonify({
            'total_papers': len(all_papers),
            'favorites': sum(1 for p in all_papers if p.is_favorite),
            'reading': sum(1 for p in all_papers if p.status == 'reading'),
            'completed': sum(1 for p in all_papers if p.status == 'completed'),
            'notes': notes_count,
            'recent_papers': [{
                'id': p.id, 'title': p.title, 'authors': p.authors,
                'year': p.year, 'status': p.status, 'is_favorite': p.is_favorite
            } for p in recent]
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
