from main import db, app

# Initialize database
with app.app_context():
    db.create_all()
    print("Database initialized successfully!")
