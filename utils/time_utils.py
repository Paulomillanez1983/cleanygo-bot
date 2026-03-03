from datetime import datetime, timedelta
from config import logger

def parse_time_string(time_str: str) -> datetime:
    """Convierte '14:30 PM' a objeto datetime de hoy"""
    try:
        time_str = time_str.strip().upper()
        is_pm = "PM" in time_str
        is_am = "AM" in time_str
        
        time_clean = time_str.replace("AM", "").replace("PM", "").strip()
        
        if ":" in time_clean:
            hour, minute = map(int, time_clean.split(":"))
        else:
            hour = int(time_clean)
            minute = 0
        
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0
            
        now = datetime.now()
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except Exception as e:
        logger.error(f"Error parseando hora {time_str}: {e}")
        return datetime.now()

def is_time_overlap(time1: str, time2: str, duration_hours: int = 2) -> bool:
    """Verifica si dos horarios se solapan"""
    try:
        dt1 = parse_time_string(time1)
        dt2 = parse_time_string(time2)
        
        start1 = dt1
        end1 = dt1 + timedelta(hours=duration_hours)
        start2 = dt2
        end2 = dt2 + timedelta(hours=duration_hours)
        
        return (start1 < end2) and (start2 < end1)
    except Exception as e:
        logger.error(f"Error comparando horarios: {e}")
        return False

