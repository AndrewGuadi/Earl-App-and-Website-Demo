from datetime import datetime

from .extensions import db


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class ServiceCategory(db.Model):
    __tablename__ = "service_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AvailabilitySlot(db.Model):
    __tablename__ = "availability_slots"

    id = db.Column(db.Integer, primary_key=True)
    weekday = db.Column(db.Integer, nullable=False, index=True)  # 0=Mon ... 6=Sun
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("weekday", "start_time", name="uq_availability_weekday_time"),
    )


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(120), nullable=False)
    service_category_id = db.Column(
        db.Integer,
        db.ForeignKey("service_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    appointment_date = db.Column(db.Date, nullable=False, index=True)
    appointment_time = db.Column(db.String(20), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    consent_text = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    service_category = db.relationship("ServiceCategory", backref="bookings")

    def to_dict(self):
        return {
            "id": self.id,
            "service": self.service,
            "serviceCategoryId": self.service_category_id,
            "durationMinutes": self.duration_minutes,
            "date": self.appointment_date.isoformat(),
            "time": self.appointment_time,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "notes": self.notes,
            "consentText": self.consent_text,
            "createdAt": self.created_at.isoformat(),
        }


class Coupon(db.Model):
    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    code = db.Column(db.String(60), nullable=True)
    image_filename = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
