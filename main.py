import os
import sys
import json
import base64
from datetime import datetime

import torch
from torch.utils.data import DataLoader

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy

from werkzeug.security import generate_password_hash, check_password_hash

from ase import io
from ase.optimize import BFGS
from ase.calculators.lj import LennardJones

# Ensure predict_energy can be found if it's in the parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forms import SignupForm, LoginForm
from predict_energy.main import load_model, predict
from predict_energy.input_file import parse_file

# Initialize Flask and database
app = Flask(__name__)
app.config['SECRET_KEY'] = 'SECRET KEY'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///catalyst.db'  # Change this to your database URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    # Relationship to History
    history = db.relationship('History', backref='user', lazy=True)


# Define the History model
class History(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    predicted_energy = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.String(255), nullable=False)

    # Foreign Key referencing the User
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    relaxed_positions = db.relationship('RelaxedPositions', backref='history', cascade='all, delete-orphan', lazy=True)


class RelaxedPositions(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    history_id = db.Column(db.Integer, db.ForeignKey('history.id'), nullable=False)
    atomic_number = db.Column(db.Integer, nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    z = db.Column(db.Float, nullable=False)


# Create the database and tables
with app.app_context():
    db.create_all()

sys.path.append(r'C:\Users\Admin\predict_energy')

# Define the folder where files will be saved
UPLOAD_FOLDER = './static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Add this configuration to Flask
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# In-memory history to store predictions
history = []

# Load your pre-trained GNN model
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model_path = r"C:\Users\Admin\readlmdb\best_model.pth"
model = load_model(model_path, device)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data).first()
        if existing_user:
            flash('Email is already registered.', 'danger')
            return redirect(url_for('signup'))
        hash_and_salted_password = generate_password_hash(
            form.password.data,
            method='pbkdf2:sha256',
            salt_length=8
        )
        new_user = User(name=form.name.data, email=form.email.data, password=hash_and_salted_password)
        db.session.add(new_user)
        db.session.commit()
        flash('Account created successfully. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password, form.password.data):
            session['user_id'] = user.id
            flash('Logged in successfully!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form)


@app.route('/home')
def home():
    return render_template('home.html')


@app.route('/predict', methods=['POST'])
def predict_relaxed_energy():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 400
    if 'cif_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['cif_file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

        # Get file extension and validate
    allowed_extensions = ['.cif', '.vasp', '.xyz']
    file_extension = os.path.splitext(file.filename)[-1].lower()
    if file_extension not in allowed_extensions:
        return jsonify({'error': f'Invalid file format. Allowed formats: {", ".join(allowed_extensions)}'}), 400

    filename = file.filename
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        if file_extension == '.cif':
            structure = io.read(file_path, format='cif')
        elif file_extension == '.vasp':
            structure = io.read(file_path, format='vasp')
        elif file_extension == '.xyz':
            structure = io.read(file_path, format='xyz')

        atomic_numbers, positions = parse_file(file_path)
        example_data_point = {'atomic_numbers': atomic_numbers, 'pos': positions}
        prediction = predict(model, example_data_point, device)
        result = prediction.item()

        structure.set_calculator(LennardJones())
        optimizer = BFGS(structure)
        optimizer.run(fmax=0.05)
        relaxed_positions = structure.get_positions()

        # Save to database
        user_id = session['user_id']
        history_entry = History(
            file_name=filename,
            predicted_energy=result,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            user_id=user_id
        )
        db.session.add(history_entry)
        db.session.commit()
        # Save relaxed positions
        for atomic_num, pos in zip(atomic_numbers, relaxed_positions):
            relaxed_entry = RelaxedPositions(
                history_id=history_entry.id,
                atomic_number=int(atomic_num),  # Convert tensor to int
                x=float(pos[0]),  # Convert tensor to float
                y=float(pos[1]),  # Convert tensor to float
                z=float(pos[2])  # Convert tensor to float
            )

            db.session.add(relaxed_entry)

        db.session.commit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'prediction': result, 'relaxed_positions': relaxed_positions.tolist()})


@app.route('/history_page')
def history_page():
    return render_template('history.html')


@app.route('/history', methods=['GET'])
def get_history():
    if 'user_id' not in session:
        return jsonify({'error': 'User not logged in'}), 400

    user_id = session['user_id']
    user_history = History.query.filter_by(user_id=user_id).all()
    history = [
        {
            'id': entry.id,
            'file_name': entry.file_name,
            'predicted_energy': entry.predicted_energy,
            'timestamp': entry.timestamp,
        }
        for entry in user_history
    ]
    return jsonify(history)


@app.route('/visualize', methods=['POST'])
def visualize_structure():
    if 'cif_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['cif_file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    try:
        structure = io.read(file_path)
        symbols = structure.get_chemical_symbols()
        positions = structure.get_positions()

        atoms_json = [{'elem': symbol, 'x': pos[0], 'y': pos[1], 'z': pos[2]} for symbol, pos in
                      zip(symbols, positions)]
        history_entry = History.query.filter_by(file_name=file.filename).first()
        relaxed_atoms_json = []
        if history_entry:
            relaxed_positions = RelaxedPositions.query.filter_by(history_id=history_entry.id).all()
            relaxed_atoms_json = [{'elem': symbols[i], 'x': pos.x, 'y': pos.y, 'z': pos.z}
                                  for i, pos in enumerate(relaxed_positions)]

        return jsonify({'atoms': atoms_json, 'relaxed_atoms': relaxed_atoms_json})



    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_relaxed_structure', methods=['GET'])
def get_relaxed_structure():
    file_id = request.args.get('id')
    if not file_id:
        return jsonify({'error': 'File ID is required'}), 400

    # Fetch history entry
    record = History.query.get(file_id)
    if not record:
        return jsonify({'error': 'File not found'}), 404

    # Fetch associated relaxed positions
    relaxed_positions = RelaxedPositions.query.filter_by(history_id=file_id).all()
    if not relaxed_positions:
        return jsonify({'error': 'No relaxed positions found'}), 404

    # Convert to JSON format
    relaxed_positions_data = [
        {'atomic_number': pos.atomic_number, 'x': pos.x, 'y': pos.y, 'z': pos.z}
        for pos in relaxed_positions
    ]

    return jsonify({'relaxed_positions': relaxed_positions_data})


@app.route('/history/<int:id>', methods=['DELETE'])
def delete_history_entry(id):
    try:
        entry = History.query.get_or_404(id)
        db.session.delete(entry)
        db.session.commit()
        return jsonify({'message': 'Entry deleted successfully'}), 200
    except Exception as e:
        db.session.rollback()  # Important: Rollback on error
        return jsonify({'error': str(e)}), 500


@app.route('/compare')
def compare():
    return render_template('compare.html')

@app.route('/guide')
def guide():
    return render_template('tutorial.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route("/logout")
def logout():
    return render_template("index.html")


if __name__ == '__main__':
    app.run(debug=True)
