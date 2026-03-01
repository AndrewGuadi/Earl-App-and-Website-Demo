import calendar
import os
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from config import Config

from .extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from .models import (  # noqa: F401
        AvailabilitySlot,
        Booking,
        Coupon,
        Customer,
        ServiceCategory,
    )

    app.config["COUPON_UPLOAD_SUBDIR"] = "uploads/coupons"
    app.config["ALLOWED_COUPON_IMAGE_EXTENSIONS"] = {"png", "jpg", "jpeg", "webp", "gif"}

    def normalize_phone(raw_phone):
        digits = "".join(ch for ch in (raw_phone or "") if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            return digits[1:]
        if len(digits) == 10:
            return digits
        return None

    def coupon_upload_folder():
        return os.path.join(app.static_folder, app.config["COUPON_UPLOAD_SUBDIR"])

    def allowed_coupon_image(filename):
        if "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[1].lower()
        return ext in app.config["ALLOWED_COUPON_IMAGE_EXTENSIONS"]

    def parse_time_hhmm(value):
        try:
            return datetime.strptime(value, "%H:%M").time()
        except (TypeError, ValueError):
            return None

    def parse_ampm_time(value):
        try:
            return datetime.strptime(value, "%I:%M %p").time()
        except (TypeError, ValueError):
            return None

    def to_ampm(t_obj):
        return t_obj.strftime("%I:%M %p").lstrip("0")

    def datetime_for(booking_date, booking_time_str):
        parsed = parse_ampm_time(booking_time_str)
        if not parsed:
            parsed = parse_time_hhmm(booking_time_str)
        if not parsed:
            return None
        return datetime.combine(booking_date, parsed)

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("admin_logged_in"):
                flash("Please log in to access admin.", "warning")
                return redirect(url_for("admin_login"))
            return fn(*args, **kwargs)

        return wrapper

    def get_service_category_or_none(service_category_id):
        if not service_category_id:
            return None
        return db.session.get(ServiceCategory, service_category_id)

    def get_day_slots(target_date):
        rows = (
            AvailabilitySlot.query.filter_by(
                weekday=target_date.weekday(),
                is_active=True,
            )
            .order_by(AvailabilitySlot.start_time.asc())
            .all()
        )
        slots = []
        for row in rows:
            parsed = parse_time_hhmm(row.start_time)
            if parsed:
                slots.append(parsed)
        return slots

    def get_bookings_for_date(target_date):
        return Booking.query.filter_by(appointment_date=target_date).all()

    def slot_is_open(target_date, slot_time_obj, requested_duration):
        start_dt = datetime.combine(target_date, slot_time_obj)
        end_dt = start_dt + timedelta(minutes=requested_duration)

        for booking in get_bookings_for_date(target_date):
            existing_start = datetime_for(target_date, booking.appointment_time)
            if not existing_start:
                continue
            existing_end = existing_start + timedelta(minutes=booking.duration_minutes or 60)
            overlaps = start_dt < existing_end and existing_start < end_dt
            if overlaps:
                return False
        return True

    def available_slots_for(service_category, target_date):
        if target_date < date.today():
            return []

        if not service_category or not service_category.is_active:
            return []

        requested_duration = max(15, int(service_category.duration_minutes or 60))
        day_slots = get_day_slots(target_date)
        result = []
        for slot_time_obj in day_slots:
            if slot_is_open(target_date, slot_time_obj, requested_duration):
                result.append(to_ampm(slot_time_obj))
        return result

    def seed_defaults_if_needed():
        # Safe no-op before migrations are applied.
        if not db.inspect(db.engine).has_table("service_categories"):
            return
        if not db.inspect(db.engine).has_table("availability_slots"):
            return
        has_coupons = db.inspect(db.engine).has_table("coupons")

        if ServiceCategory.query.count() == 0:
            db.session.add_all(
                [
                    ServiceCategory(name="Emergency Leak Repair", duration_minutes=120),
                    ServiceCategory(name="Drain Cleaning", duration_minutes=90),
                    ServiceCategory(name="Water Heater Service", duration_minutes=120),
                    ServiceCategory(name="General Plumbing", duration_minutes=60),
                ]
            )

        if AvailabilitySlot.query.count() == 0:
            default_weekday_slots = {
                0: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                1: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                2: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                3: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                4: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"],
                5: ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00"],
                6: [],
            }
            for weekday, start_times in default_weekday_slots.items():
                for start_time in start_times:
                    db.session.add(
                        AvailabilitySlot(weekday=weekday, start_time=start_time, is_active=True)
                    )

        if has_coupons and Coupon.query.count() == 0:
            db.session.add_all(
                [
                    Coupon(
                        title="$50 OFF",
                        description="Any Plumbing Repair (minimum $250).",
                        code="SAVE50",
                        is_active=True,
                    ),
                    Coupon(
                        title="$100 OFF",
                        description="Water Heater Installation discount.",
                        code="HOT100",
                        is_active=True,
                    ),
                    Coupon(
                        title="FREE",
                        description="Camera inspection with paid main line cleaning.",
                        code="SEWERFREE",
                        is_active=True,
                    ),
                ]
            )

        db.session.commit()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.get("/api/flashes")
    def api_flashes():
        messages = get_flashed_messages(with_categories=True)
        payload = [{"category": c, "message": m} for c, m in messages]
        return jsonify({"messages": payload})

    @app.get("/api/service-categories")
    def service_categories():
        rows = (
            ServiceCategory.query.filter_by(is_active=True)
            .order_by(ServiceCategory.name.asc())
            .all()
        )
        return jsonify(
            {
                "categories": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "durationMinutes": row.duration_minutes,
                    }
                    for row in rows
                ]
            }
        )

    @app.get("/api/coupons")
    def coupons():
        rows = Coupon.query.filter_by(is_active=True).order_by(Coupon.created_at.desc()).all()
        return jsonify(
            {
                "coupons": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "description": row.description,
                        "code": row.code,
                        "imageUrl": (
                            url_for(
                                "static",
                                filename=f"{app.config['COUPON_UPLOAD_SUBDIR']}/{row.image_filename}",
                            )
                            if row.image_filename
                            else None
                        ),
                    }
                    for row in rows
                ]
            }
        )

    @app.get("/api/bookings/availability")
    def booking_availability():
        service_category_id = request.args.get("service_id", type=int)
        category = get_service_category_or_none(service_category_id)
        date_str = request.args.get("date")

        if date_str:
            try:
                target_date = date.fromisoformat(date_str)
            except ValueError:
                return jsonify({"error": "Invalid date. Use YYYY-MM-DD."}), 400

            available_times = available_slots_for(category, target_date)
            booked_times = sorted(
                [b.appointment_time for b in get_bookings_for_date(target_date)]
            )
            return jsonify(
                {
                    "date": target_date.isoformat(),
                    "available_times": available_times,
                    "booked_times": booked_times,
                }
            )

        year = request.args.get("year", type=int)
        month = request.args.get("month", type=int)
        if not year or not month or month < 1 or month > 12:
            return jsonify({"error": "Provide either date or valid year/month."}), 400

        _, days_in_month = calendar.monthrange(year, month)
        availability = {}
        for day_num in range(1, days_in_month + 1):
            current_date = date(year, month, day_num)
            availability[current_date.isoformat()] = len(
                available_slots_for(category, current_date)
            )

        return jsonify({"year": year, "month": month, "availability": availability})

    @app.post("/api/bookings")
    def create_booking():
        payload = request.get_json(silent=True) or {}

        required_fields = [
            "serviceCategoryId",
            "date",
            "time",
            "firstName",
            "lastName",
            "phone",
            "address",
        ]
        missing = [field for field in required_fields if not str(payload.get(field, "")).strip()]
        if missing:
            message = f"Missing required fields: {', '.join(missing)}"
            flash(message, "error")
            return jsonify({"error": message}), 400

        category = get_service_category_or_none(int(payload.get("serviceCategoryId")))
        if not category or not category.is_active:
            message = "Selected service category is invalid."
            flash(message, "error")
            return jsonify({"error": message}), 400

        try:
            appointment_date = date.fromisoformat(payload["date"])
        except ValueError:
            message = "Invalid date. Use YYYY-MM-DD."
            flash(message, "error")
            return jsonify({"error": message}), 400

        if appointment_date < date.today():
            message = "Cannot book a past date."
            flash(message, "error")
            return jsonify({"error": message}), 400

        phone = normalize_phone(payload.get("phone"))
        if not phone:
            message = "Phone number must be 10 digits."
            flash(message, "error")
            return jsonify({"error": message}), 400

        appointment_time = payload.get("time", "").strip()
        allowed_slots = available_slots_for(category, appointment_date)
        if appointment_time not in allowed_slots:
            message = "Selected time is no longer available."
            flash(message, "error")
            return jsonify({"error": message, "available_times": allowed_slots}), 409

        booking = Booking(
            service=category.name,
            service_category_id=category.id,
            duration_minutes=category.duration_minutes,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            first_name=payload.get("firstName", "").strip(),
            last_name=payload.get("lastName", "").strip(),
            phone=phone,
            email=(payload.get("email") or "").strip() or None,
            address=payload.get("address", "").strip(),
            notes=(payload.get("notes") or "").strip() or None,
            consent_text=bool(payload.get("consentText", False)),
        )

        db.session.add(booking)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            fresh_available = available_slots_for(category, appointment_date)
            message = "Selected time was just booked by another request."
            flash(message, "error")
            return jsonify({"error": message, "available_times": fresh_available}), 409

        success_message = "Booking request sent successfully."
        flash(success_message, "success")
        return jsonify({"booking": booking.to_dict(), "message": success_message}), 201

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if (
                username == app.config.get("ADMIN_USERNAME", "admin")
                and password == app.config.get("ADMIN_PASSWORD", "change-me")
            ):
                session["admin_logged_in"] = True
                flash("Admin login successful.", "success")
                return redirect(url_for("admin_dashboard"))

            flash("Invalid admin credentials.", "error")

        return render_template("admin/login.html")

    @app.get("/admin/logout")
    @admin_required
    def admin_logout():
        session.pop("admin_logged_in", None)
        flash("Logged out.", "success")
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        categories = ServiceCategory.query.order_by(ServiceCategory.name.asc()).all()
        slots = AvailabilitySlot.query.order_by(
            AvailabilitySlot.weekday.asc(),
            AvailabilitySlot.start_time.asc(),
        ).all()
        coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
        return render_template(
            "admin/dashboard.html",
            categories=categories,
            slots=slots,
            coupons=coupons,
            weekday_names=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        )

    @app.post("/admin/categories")
    @admin_required
    def admin_add_category():
        name = (request.form.get("name") or "").strip()
        duration_raw = request.form.get("duration_minutes", "60")

        try:
            duration_minutes = int(duration_raw)
        except ValueError:
            duration_minutes = 0

        if not name or duration_minutes < 15:
            flash("Category name and duration (15+ minutes) are required.", "error")
            return redirect(url_for("admin_dashboard"))

        exists = ServiceCategory.query.filter(ServiceCategory.name.ilike(name)).first()
        if exists:
            flash("Category already exists.", "error")
            return redirect(url_for("admin_dashboard"))

        db.session.add(
            ServiceCategory(name=name, duration_minutes=duration_minutes, is_active=True)
        )
        db.session.commit()
        flash("Category added.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/categories/<int:category_id>/toggle")
    @admin_required
    def admin_toggle_category(category_id):
        category = db.session.get(ServiceCategory, category_id)
        if not category:
            flash("Category not found.", "error")
            return redirect(url_for("admin_dashboard"))

        category.is_active = not category.is_active
        db.session.commit()
        flash("Category updated.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/slots")
    @admin_required
    def admin_add_slot():
        weekday = request.form.get("weekday", type=int)
        start_time = (request.form.get("start_time") or "").strip()

        if weekday is None or weekday < 0 or weekday > 6:
            flash("Valid weekday is required.", "error")
            return redirect(url_for("admin_dashboard"))

        if not parse_time_hhmm(start_time):
            flash("Time must be in HH:MM format.", "error")
            return redirect(url_for("admin_dashboard"))

        slot = AvailabilitySlot(weekday=weekday, start_time=start_time, is_active=True)
        db.session.add(slot)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That weekday/time slot already exists.", "error")
            return redirect(url_for("admin_dashboard"))

        flash("Availability slot added.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/slots/<int:slot_id>/toggle")
    @admin_required
    def admin_toggle_slot(slot_id):
        slot = db.session.get(AvailabilitySlot, slot_id)
        if not slot:
            flash("Slot not found.", "error")
            return redirect(url_for("admin_dashboard"))

        slot.is_active = not slot.is_active
        db.session.commit()
        flash("Slot updated.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/coupons")
    @admin_required
    def admin_add_coupon():
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        code = (request.form.get("code") or "").strip() or None
        image_file = request.files.get("image")
        image_filename = None

        if not title:
            flash("Coupon title is required.", "error")
            return redirect(url_for("admin_dashboard"))

        if image_file and image_file.filename:
            if not allowed_coupon_image(image_file.filename):
                flash("Coupon image must be png, jpg, jpeg, webp, or gif.", "error")
                return redirect(url_for("admin_dashboard"))
            safe_name = secure_filename(image_file.filename)
            ext = safe_name.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            os.makedirs(coupon_upload_folder(), exist_ok=True)
            image_file.save(os.path.join(coupon_upload_folder(), image_filename))

        db.session.add(
            Coupon(
                title=title,
                description=description,
                code=code,
                image_filename=image_filename,
                is_active=True,
            )
        )
        db.session.commit()
        flash("Coupon added.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/coupons/<int:coupon_id>/toggle")
    @admin_required
    def admin_toggle_coupon(coupon_id):
        coupon = db.session.get(Coupon, coupon_id)
        if not coupon:
            flash("Coupon not found.", "error")
            return redirect(url_for("admin_dashboard"))

        coupon.is_active = not coupon.is_active
        db.session.commit()
        flash("Coupon updated.", "success")
        return redirect(url_for("admin_dashboard"))

    os.makedirs(coupon_upload_folder(), exist_ok=True)

    with app.app_context():
        seed_defaults_if_needed()

    return app
