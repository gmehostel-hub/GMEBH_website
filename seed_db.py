import os
import sys
from bson import ObjectId
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

# Add the current directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the Flask app and database connection
from app import app, mongo

def seed_database():
    # Ensure we're connected to the database
    try:
        # This will raise an exception if connection fails
        mongo.db.command('ping')
        print("Successfully connected to MongoDB!")
    except Exception as e:
        print(f"Error connecting to MongoDB: {e}")
        print("Please check your MongoDB connection string in .env file")
        return
    print("Starting database seeding...")
    
    # Clear existing data
    print("Clearing existing data...")
    mongo.db.users.delete_many({})
    mongo.db.rooms.delete_many({})
    mongo.db.books.delete_many({})
    
    # Create admin user
    admin = {
        'name': 'Admin User',
        'email': 'admin@hostel.com',
        'password': generate_password_hash('admin123'),
        'role': 'admin',
        'phone': '+919876543210',
        'created_at': datetime.utcnow(),
        'status': 'active'
    }
    mongo.db.users.insert_one(admin)
    print("Created admin user")
    
    # Create warden
    warden = {
        'name': 'Warden',
        'email': 'warden@hostel.com',
        'password': generate_password_hash('warden123'),
        'role': 'warden',
        'phone': '+919876543211',
        'created_at': datetime.utcnow(),
        'status': 'active'
    }
    mongo.db.users.insert_one(warden)
    print("Created warden user")

    # Create rooms
    print("Creating rooms...")
    rooms = []
    def mk_room(num, floor, rtype, capacity, rent, status='available', desc=''):
        return {
            'room_number': num,
            'floor': floor,               # 'ground', '1', '2', ...
            'room_type': rtype,           # e.g., 'single', 'double', 'triple'
            'capacity': capacity,
            'current_occupancy': 0,
            'rent': rent,
            'description': desc,
            'status': status,
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
    rooms.extend([
        mk_room('101', 'ground', 'single', 1, 3000, 'available', 'Cozy single room near entrance.'),
        mk_room('102', 'ground', 'double', 2, 4500, 'available', 'Spacious double room.'),
        mk_room('103', 'ground', 'double', 2, 4500, 'available', 'Good ventilation.'),
        mk_room('201', '1', 'triple', 3, 6000, 'available', 'Corner triple room.'),
        mk_room('202', '1', 'single', 1, 3200, 'available', 'Quiet single room.'),
        mk_room('301', '2', 'double', 2, 4700, 'available', 'Upper floor double.'),
        mk_room('302', '2', 'triple', 3, 6200, 'available', 'Bright triple room.')
    ])
    room_ids = mongo.db.rooms.insert_many(rooms).inserted_ids
    print(f"Inserted {len(room_ids)} rooms")

    # Create students
    print("Creating students...")
    students = []
    def mk_student(i, assigned_room=None):
        year = (i % 4) + 1
        streams = ['engineering', 'medical']
        stream = streams[i % len(streams)]
        branches = ['CSE', 'ECE', 'ME', 'CE', 'EE']
        branch = branches[i % len(branches)]
        doc = {
            'name': f'Student {i}',
            'email': f'student{i}@test.com',
            'password': generate_password_hash('student123'),
            'role': 'student',
            'phone': f'+919876540{str(i).zfill(3)}',
            'year': year,
            'stream': stream,
            'branch': branch,
            'college': 'ABC Institute of Technology',
            'swd_id': f'SWD{1000+i}',
            'created_at': datetime.utcnow(),
            'status': 'active'
        }
        if assigned_room:
            doc['room_number'] = assigned_room
        return doc

    # Assign first few students to rooms to simulate occupancy
    assign_plan = ['101', '102', '102', '103', '201', '201', '201']  # fills capacities appropriately
    for i in range(1, 21):
        rn = assign_plan[i-1] if i-1 < len(assign_plan) else None
        students.append(mk_student(i, rn))

    mongo.db.users.insert_many(students)
    print(f"Inserted {len(students)} students")

    # Update room occupancies based on assigned students
    print("Updating room occupancies...")
    pipeline = [
        {'$match': {'role': 'student', 'room_number': {'$exists': True}}},
        {'$group': {'_id': '$room_number', 'count': {'$sum': 1}}}
    ]
    for rec in mongo.db.users.aggregate(pipeline):
        rn = rec['_id']
        cnt = rec['count']
        mongo.db.rooms.update_one({'room_number': rn}, {'$set': {'current_occupancy': cnt, 'status': 'occupied' if cnt > 0 else 'available', 'updated_at': datetime.utcnow()}})

    # Create books
    print("Creating books...")
    books = []
    def mk_book(idx, status='available'):
        return {
            'book_id': f'BK-{idx:04d}',
            'title': f'Introduction to Topic {idx}',
            'author': f'Author {idx}',
            'price': round(100 + (idx * 7.5), 2),
            'status': status,
            'created_at': datetime.utcnow()
        }
    for i in range(1, 26):
        books.append(mk_book(i, 'available' if i % 5 else 'issued'))
    mongo.db.books.insert_many(books)
    print(f"Inserted {len(books)} books")

    print("\nTest accounts:")
    print("Admin: admin@hostel.com / admin123")
    print("Warden: warden@hostel.com / warden123")
    print("Students: student1@test.com to student20@test.com / student123")

if __name__ == '__main__':
    with app.app_context():
        seed_database()
