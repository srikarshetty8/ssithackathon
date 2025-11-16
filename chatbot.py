"""
CarbonBuddy - In-app assistant for Carbon Footprint Tracker
Accepts user activity inputs, calculates CO₂e emissions, stores history,
compares date ranges and cities, and produces summaries.
"""

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import os
import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import google.generativeai as genai  # Optional: for Gemini API integration

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
USE_GEMINI = os.getenv('USE_GEMINI', 'false').lower() == 'true'
MOCK_MODE = os.getenv('MOCK_MODE', 'true').lower() == 'true'

if GEMINI_API_KEY and USE_GEMINI:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')

# In-memory storage (replace with database in production)
history_db: Dict[str, List[Dict]] = {}  # {user_id: [entries]}
emission_factors_db: Dict[str, float] = {}

# Default emission factors (kg CO2e per km)
DEFAULT_EMISSION_FACTORS = {
    'car': 0.192,
    'motorcycle': 0.103,
    'scooter': 0.103,
    'bus': 0.089,
    'train': 0.041,
    'bicycle': 0.000,
    'bike': 0.000,
    'walking': 0.000,
    'walk': 0.000,
}

# City synonyms normalization
CITY_SYNONYMS = {
    'delhi': ['new delhi', 'ncr', 'national capital region'],
    'bengaluru': ['bangalore', 'bengaluru'],
    'mumbai': ['bombay'],
    'kolkata': ['calcutta'],
    'chennai': ['madras'],
}

# Initialize emission factors
emission_factors_db.update(DEFAULT_EMISSION_FACTORS)


def normalize_city(city: str) -> Optional[str]:
    """Normalize city name using synonyms."""
    if not city:
        return None
    
    city_lower = city.lower().strip()
    
    # Direct match
    if city_lower in CITY_SYNONYMS:
        return city_lower
    
    # Check synonyms
    for canonical, synonyms in CITY_SYNONYMS.items():
        if city_lower == canonical or city_lower in synonyms:
            return canonical
    
    return city_lower


def parse_natural_language(message: str) -> Dict:
    """
    Parse natural language to extract activity data.
    Examples:
    - "I rode a car 12.5 km today in Delhi"
    - "Add: car 25km Delhi 2025-10-02"
    - "I took the bus 8 km in Bengaluru today"
    """
    message_lower = message.lower()
    parsed = {
        'category': None,
        'subcategory': None,
        'distance_km': None,
        'amount': None,
        'units': None,
        'city': None,
        'date': None,
    }
    
    # Extract date patterns
    date_patterns = [
        r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
        r'(today|yesterday|tomorrow)',
        r'(last\s+month|this\s+month|next\s+month)',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, message_lower)
        if match:
            date_str = match.group(1)
            if date_str == 'today':
                parsed['date'] = datetime.now().strftime('%Y-%m-%d')
            elif date_str == 'yesterday':
                parsed['date'] = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            elif date_str.startswith('202'):
                parsed['date'] = date_str
            break
    
    # Extract distance
    distance_patterns = [
        r'(\d+\.?\d*)\s*(?:km|kilometer|kilometers)',
        r'(\d+\.?\d*)\s*(?:mile|miles)',
    ]
    for pattern in distance_patterns:
        match = re.search(pattern, message_lower)
        if match:
            distance = float(match.group(1))
            if 'mile' in match.group(0):
                distance = distance * 1.60934  # Convert miles to km
            parsed['distance_km'] = distance
            break
    
    # Extract transport type
    transport_keywords = {
        'car': ['car', 'vehicle', 'auto'],
        'bus': ['bus'],
        'train': ['train', 'railway'],
        'motorcycle': ['motorcycle', 'bike', 'scooter'],
        'bicycle': ['bicycle', 'cycle', 'bike'],
        'walking': ['walk', 'walked', 'walking'],
    }
    
    for subcat, keywords in transport_keywords.items():
        if any(kw in message_lower for kw in keywords):
            parsed['category'] = 'transport'
            parsed['subcategory'] = subcat
            break
    
    # Extract city
    city_patterns = [
        r'in\s+([A-Za-z\s]+?)(?:\s|$|,|\.)',
        r'([A-Za-z\s]+?)\s+(?:on|for|in)\s+\d{4}',
    ]
    for pattern in city_patterns:
        match = re.search(pattern, message)
        if match:
            city = match.group(1).strip()
            normalized = normalize_city(city)
            if normalized:
                parsed['city'] = normalized
                break
    
    # Extract amount for non-transport
    amount_patterns = [
        r'(\d+\.?\d*)\s*(?:kg|kg|items|rs|inr|rupees?)',
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, message_lower)
        if match:
            parsed['amount'] = float(match.group(1))
            break
    
    return parsed


def calculate_emissions(entry: Dict) -> float:
    """Calculate emissions_kg for an entry."""
    category = entry.get('category')
    
    if category == 'transport' and entry.get('distance_km'):
        subcategory = entry.get('subcategory', 'car')
        # Check for override factor
        factor = entry.get('emission_factor_override')
        if not factor:
            # Get from emission factors DB
            factor = emission_factors_db.get(subcategory)
            if not factor:
                # Try variations
                for key, value in emission_factors_db.items():
                    if subcategory.lower() in key.lower() or key.lower() in subcategory.lower():
                        factor = value
                        break
        
        if factor is None:
            raise ValueError(f"No emission factor found for subcategory: {subcategory}")
        
        return entry['distance_km'] * factor
    
    # For non-transport categories, require amount and factor
    elif entry.get('amount') and entry.get('emission_factor'):
        return entry['amount'] * entry['emission_factor']
    
    return 0.0


def logEntry(payload: Dict, user_id: Optional[str] = None) -> Dict:
    """Log an entry and calculate emissions."""
    # Validate required fields
    category = payload.get('category')
    if not category:
        return {
            'success': False,
            'human_message': 'Error: Category is required. Please specify transport, food, shopping, energy, or other.',
            'data': {'error': 'Missing category'}
        }
    
    # If payload looks like natural language, parse it
    if 'message' in payload or 'text' in payload:
        message = payload.get('message') or payload.get('text')
        parsed = parse_natural_language(message)
        # Merge parsed data with payload
        for key, value in parsed.items():
            if value and not payload.get(key):
                payload[key] = value
    
    # Set defaults
    entry = {
        'id': str(uuid.uuid4()),
        'user_id': user_id or 'anonymous',
        'date': payload.get('date') or datetime.now().strftime('%Y-%m-%d'),
        'category': category,
        'subcategory': payload.get('subcategory'),
        'distance_km': payload.get('distance_km'),
        'amount': payload.get('amount'),
        'units': payload.get('units'),
        'city': normalize_city(payload.get('city')) if payload.get('city') else None,
        'notes': payload.get('notes'),
        'emission_factor_override': payload.get('emission_factor'),
    }
    
    # Validate transport entries
    if category == 'transport':
        if entry['distance_km'] is None:
            return {
                'success': False,
                'human_message': 'Error: Distance (km) is required for transport entries.',
                'data': {'error': 'Missing distance_km'}
            }
        if entry['distance_km'] < 0:
            return {
                'success': False,
                'human_message': 'Error: Distance cannot be negative.',
                'data': {'error': 'Invalid distance'}
            }
    
    # Calculate emissions
    try:
        entry['emissions_kg'] = calculate_emissions(entry)
    except ValueError as e:
        subcategory = entry.get('subcategory', 'unknown')
        suggested_factor = DEFAULT_EMISSION_FACTORS.get(subcategory, 0.192)
        return {
            'success': False,
            'human_message': f'Error: No emission factor found for {subcategory}. Please provide an emission_factor in the request. Suggested factor: {suggested_factor} kg CO₂e per km.',
            'data': {'error': str(e), 'suggested_factor': suggested_factor}
        }
    
    entry['created_at'] = datetime.now().isoformat() + 'Z'
    
    # Store entry
    if entry['user_id'] not in history_db:
        history_db[entry['user_id']] = []
    history_db[entry['user_id']].append(entry)
    
    # Generate human message
    subcat = entry.get('subcategory', entry.get('category', 'activity'))
    distance = entry.get('distance_km')
    city = entry.get('city', '').title() if entry.get('city') else ''
    date = entry['date']
    emissions = entry['emissions_kg']
    
    if distance:
        human_msg = f"Logged: {subcat.title()} — {distance:.1f} km on {date}"
        if city:
            human_msg += f" in {city}"
        human_msg += f" → {emissions:.2f} kg CO₂e."
    else:
        amount = entry.get('amount', 0)
        units = entry.get('units', 'items')
        human_msg = f"Logged: {subcat.title()} — {amount} {units} on {date} → {emissions:.2f} kg CO₂e."
    
    return {
        'success': True,
        'human_message': human_msg,
        'data': {'entry': entry}
    }


def getHistory(user_id: Optional[str] = None, start_date: Optional[str] = None,
               end_date: Optional[str] = None, city: Optional[str] = None,
               category: Optional[str] = None, detailed: bool = True) -> Dict:
    """Get history with filters, totals, and detailed breakdowns."""
    user_id = user_id or 'anonymous'
    entries = history_db.get(user_id, [])
    
    # Apply filters
    filtered = []
    for entry in entries:
        if start_date and entry['date'] < start_date:
            continue
        if end_date and entry['date'] > end_date:
            continue
        if city and entry.get('city') != normalize_city(city):
            continue
        if category and entry['category'] != category:
            continue
        filtered.append(entry)
    
    # Sort by date descending
    filtered.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate totals
    total_emissions_kg = sum(e['emissions_kg'] for e in filtered)
    by_category = defaultdict(float)
    for entry in filtered:
        by_category[entry['category']] += entry['emissions_kg']
    
    # Detailed breakdowns
    detailed_breakdown = {}
    if detailed:
        # Transport: km per vehicle
        vehicle_km = defaultdict(float)
        vehicle_emissions = defaultdict(float)
        vehicle_trips = defaultdict(int)
        
        for entry in filtered:
            if entry['category'] == 'transport' and entry.get('distance_km'):
                subcat = entry.get('subcategory', 'unknown')
                vehicle_km[subcat] += entry['distance_km']
                vehicle_emissions[subcat] += entry['emissions_kg']
                vehicle_trips[subcat] += 1
        
        detailed_breakdown['transport'] = {
            'vehicles': [
                {
                    'vehicle': vehicle,
                    'total_km': round(km, 2),
                    'total_emissions_kg': round(vehicle_emissions[vehicle], 2),
                    'trips': vehicle_trips[vehicle],
                    'avg_km_per_trip': round(km / vehicle_trips[vehicle], 2) if vehicle_trips[vehicle] > 0 else 0
                }
                for vehicle, km in sorted(vehicle_km.items(), key=lambda x: x[1], reverse=True)
            ],
            'total_km': round(sum(vehicle_km.values()), 2),
            'total_emissions_kg': round(sum(vehicle_emissions.values()), 2)
        }
        
        # Food: consumption details
        food_items = defaultdict(float)
        food_emissions = defaultdict(float)
        food_amounts = defaultdict(float)
        
        for entry in filtered:
            if entry['category'] == 'food':
                subcat = entry.get('subcategory', 'other')
                amount = entry.get('amount', 0)
                food_items[subcat] += amount
                food_emissions[subcat] += entry['emissions_kg']
                food_amounts[subcat] += amount
        
        detailed_breakdown['food'] = {
            'items': [
                {
                    'item': item,
                    'total_amount': round(amount, 2),
                    'total_emissions_kg': round(food_emissions[item], 2),
                    'units': next((e.get('units', 'items') for e in filtered if e.get('category') == 'food' and e.get('subcategory') == item), 'items')
                }
                for item, amount in sorted(food_items.items(), key=lambda x: x[1], reverse=True)
            ],
            'total_emissions_kg': round(sum(food_emissions.values()), 2)
        }
        
        # Shopping: items and spending
        shopping_items = defaultdict(float)
        shopping_emissions = defaultdict(float)
        shopping_amounts = defaultdict(float)
        
        for entry in filtered:
            if entry['category'] == 'shopping':
                subcat = entry.get('subcategory', 'other')
                amount = entry.get('amount', 0)
                shopping_items[subcat] += amount
                shopping_emissions[subcat] += entry['emissions_kg']
                shopping_amounts[subcat] += amount
        
        detailed_breakdown['shopping'] = {
            'items': [
                {
                    'item': item,
                    'total_amount': round(amount, 2),
                    'total_emissions_kg': round(shopping_emissions[item], 2),
                    'units': next((e.get('units', 'items') for e in filtered if e.get('category') == 'shopping' and e.get('subcategory') == item), 'items')
                }
                for item, amount in sorted(shopping_items.items(), key=lambda x: x[1], reverse=True)
            ],
            'total_emissions_kg': round(sum(shopping_emissions.values()), 2)
        }
        
        # Energy breakdown
        energy_types = defaultdict(float)
        energy_emissions = defaultdict(float)
        
        for entry in filtered:
            if entry['category'] == 'energy':
                subcat = entry.get('subcategory', 'other')
                amount = entry.get('amount', 0)
                energy_types[subcat] += amount
                energy_emissions[subcat] += entry['emissions_kg']
        
        detailed_breakdown['energy'] = {
            'types': [
                {
                    'type': energy_type,
                    'total_amount': round(amount, 2),
                    'total_emissions_kg': round(energy_emissions[energy_type], 2),
                    'units': next((e.get('units', 'kWh') for e in filtered if e.get('category') == 'energy' and e.get('subcategory') == energy_type), 'kWh')
                }
                for energy_type, amount in sorted(energy_types.items(), key=lambda x: x[1], reverse=True)
            ],
            'total_emissions_kg': round(sum(energy_emissions.values()), 2)
        }
    
    # Prepare timeseries data
    timeseries = defaultdict(float)
    for entry in filtered:
        timeseries[entry['date']] += entry['emissions_kg']
    timeseries_list = [{'date': date, 'kg': kg} for date, kg in sorted(timeseries.items())]
    
    # Prepare category breakdown
    category_breakdown = []
    for cat, kg in by_category.items():
        percent = (kg / total_emissions_kg * 100) if total_emissions_kg > 0 else 0
        category_breakdown.append({
            'category': cat,
            'kg': round(kg, 2),
            'percent': round(percent, 1)
        })
    
    human_msg = f"Found {len(filtered)} entries"
    if start_date or end_date:
        human_msg += f" from {start_date or 'beginning'} to {end_date or 'now'}"
    human_msg += f". Total: {total_emissions_kg:.2f} kg CO₂e."
    
    if detailed and detailed_breakdown.get('transport'):
        transport = detailed_breakdown['transport']
        if transport['vehicles']:
            top_vehicle = transport['vehicles'][0]
            human_msg += f" Top vehicle: {top_vehicle['vehicle']} ({top_vehicle['total_km']:.1f} km)."
    
    return {
        'success': True,
        'human_message': human_msg,
        'data': {
            'entries': filtered,
            'total_emissions_kg': round(total_emissions_kg, 2),
            'by_category': dict(by_category),
            'detailed_breakdown': detailed_breakdown if detailed else {},
            'chart_ready': {
                'timeseries': timeseries_list,
                'category_breakdown': category_breakdown,
            }
        }
    }


def comparePeriods(user_id: Optional[str] = None, from_start: Optional[str] = None,
                   from_end: Optional[str] = None, to_start: Optional[str] = None,
                   to_end: Optional[str] = None, category: Optional[str] = None) -> Dict:
    """Compare emissions between two periods."""
    user_id = user_id or 'anonymous'
    
    # Get history for both periods
    from_history = getHistory(user_id, from_start, from_end, category=category)
    to_history = getHistory(user_id, to_start, to_end, category=category)
    
    from_total = from_history['data']['total_emissions_kg']
    to_total = to_history['data']['total_emissions_kg']
    
    # Calculate change
    absolute_kg = to_total - from_total
    if from_total > 0:
        percent = round((absolute_kg / from_total) * 100, 1)
    else:
        percent = None
    
    # Breakdown by subcategory for transport
    from_breakdown = defaultdict(float)
    to_breakdown = defaultdict(float)
    
    for entry in from_history['data']['entries']:
        if entry['category'] == 'transport':
            subcat = entry.get('subcategory', 'unknown')
            from_breakdown[subcat] += entry['emissions_kg']
    
    for entry in to_history['data']['entries']:
        if entry['category'] == 'transport':
            subcat = entry.get('subcategory', 'unknown')
            to_breakdown[subcat] += entry['emissions_kg']
    
    # Human message
    if percent is not None:
        if percent < 0:
            human_msg = f"Emissions decreased {abs(percent):.1f}% ({abs(absolute_kg):.2f} kg) vs previous period."
        elif percent > 0:
            human_msg = f"Emissions increased {percent:.1f}% (+{absolute_kg:.2f} kg) vs previous period."
        else:
            human_msg = f"Emissions unchanged ({to_total:.2f} kg)."
    else:
        human_msg = f"Previous period had no emissions. Current period: {to_total:.2f} kg CO₂e."
    
    return {
        'success': True,
        'human_message': human_msg,
        'from': {
            'total_emissions_kg': from_total,
            'breakdown': dict(from_breakdown),
            'period': f"{from_start} to {from_end}"
        },
        'to': {
            'total_emissions_kg': to_total,
            'breakdown': dict(to_breakdown),
            'period': f"{to_start} to {to_end}"
        },
        'change': {
            'absolute_kg': round(absolute_kg, 2),
            'percent': percent
        }
    }


def compareCities(user_id: Optional[str] = None, cityA: Optional[str] = None,
                  cityB: Optional[str] = None, start_date: Optional[str] = None,
                  end_date: Optional[str] = None, category: Optional[str] = None) -> Dict:
    """Compare emissions between two cities."""
    user_id = user_id or 'anonymous'
    
    cityA_norm = normalize_city(cityA) if cityA else None
    cityB_norm = normalize_city(cityB) if cityB else None
    
    # Get history for each city
    cityA_history = getHistory(user_id, start_date, end_date, city=cityA_norm, category=category)
    cityB_history = getHistory(user_id, start_date, end_date, city=cityB_norm, category=category)
    
    cityA_total = cityA_history['data']['total_emissions_kg']
    cityB_total = cityB_history['data']['total_emissions_kg']
    difference = cityB_total - cityA_total
    
    # Top 3 contributors per city
    cityA_contributors = defaultdict(float)
    cityB_contributors = defaultdict(float)
    
    for entry in cityA_history['data']['entries']:
        subcat = entry.get('subcategory', entry.get('category', 'other'))
        cityA_contributors[subcat] += entry['emissions_kg']
    
    for entry in cityB_history['data']['entries']:
        subcat = entry.get('subcategory', entry.get('category', 'other'))
        cityB_contributors[subcat] += entry['emissions_kg']
    
    top3_cityA = sorted(cityA_contributors.items(), key=lambda x: x[1], reverse=True)[:3]
    top3_cityB = sorted(cityB_contributors.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Conclusion
    if difference > 0:
        conclusion = f"{cityB or 'City B'} has {difference:.2f} kg more emissions than {cityA or 'City A'}."
    elif difference < 0:
        conclusion = f"{cityA or 'City A'} has {abs(difference):.2f} kg more emissions than {cityB or 'City B'}."
    else:
        conclusion = "Both cities have similar emissions."
    
    human_msg = f"{cityA or 'City A'}: {cityA_total:.2f} kg, {cityB or 'City B'}: {cityB_total:.2f} kg. {conclusion}"
    
    return {
        'success': True,
        'human_message': human_msg,
        'data': {
            'cityA': {
                'name': cityA or 'City A',
                'total_emissions_kg': cityA_total,
                'top_contributors': [{'subcategory': k, 'kg': v} for k, v in top3_cityA]
            },
            'cityB': {
                'name': cityB or 'City B',
                'total_emissions_kg': cityB_total,
                'top_contributors': [{'subcategory': k, 'kg': v} for k, v in top3_cityB]
            },
            'difference_kg': round(difference, 2),
            'conclusion': conclusion
        }
    }


def summary(user_id: Optional[str] = None, start_date: Optional[str] = None,
            end_date: Optional[str] = None) -> Dict:
    """Generate comprehensive summary with totals, detailed breakdowns, top contributors, and tips."""
    history = getHistory(user_id, start_date, end_date, detailed=True)
    
    total = history['data']['total_emissions_kg']
    by_category = history['data']['by_category']
    entries = history['data']['entries']
    detailed = history['data']['detailed_breakdown']
    
    # Top 3 contributors overall
    contributors = defaultdict(float)
    for entry in entries:
        subcat = entry.get('subcategory', entry.get('category', 'other'))
        contributors[subcat] += entry['emissions_kg']
    
    top3_contributors = sorted(contributors.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Percentage share by category
    category_shares = {}
    for cat, kg in by_category.items():
        category_shares[cat] = round((kg / total * 100) if total > 0 else 0, 1)
    
    # Generate detailed summary message
    summary_parts = []
    
    # Transport summary
    if detailed.get('transport') and detailed['transport'].get('vehicles'):
        transport = detailed['transport']
        summary_parts.append(f"🚗 Transport: {transport['total_km']:.1f} km across {len(transport['vehicles'])} vehicle types ({transport['total_emissions_kg']:.2f} kg CO₂e)")
        if transport['vehicles']:
            top_vehicle = transport['vehicles'][0]
            summary_parts.append(f"   → Top: {top_vehicle['vehicle']} ({top_vehicle['total_km']:.1f} km, {top_vehicle['trips']} trips)")
    
    # Food summary
    if detailed.get('food') and detailed['food'].get('items'):
        food = detailed['food']
        summary_parts.append(f"🍽️ Food: {len(food['items'])} item types ({food['total_emissions_kg']:.2f} kg CO₂e)")
        if food['items']:
            top_food = food['items'][0]
            summary_parts.append(f"   → Top: {top_food['item']} ({top_food['total_amount']:.1f} {top_food['units']})")
    
    # Shopping summary
    if detailed.get('shopping') and detailed['shopping'].get('items'):
        shopping = detailed['shopping']
        summary_parts.append(f"🛒 Shopping: {len(shopping['items'])} item types ({shopping['total_emissions_kg']:.2f} kg CO₂e)")
        if shopping['items']:
            top_item = shopping['items'][0]
            summary_parts.append(f"   → Top: {top_item['item']} ({top_item['total_amount']:.1f} {top_item['units']})")
    
    # Energy summary
    if detailed.get('energy') and detailed['energy'].get('types'):
        energy = detailed['energy']
        summary_parts.append(f"⚡ Energy: {len(energy['types'])} types ({energy['total_emissions_kg']:.2f} kg CO₂e)")
    
    # Generate tips
    tips = []
    top_category = max(by_category.items(), key=lambda x: x[1])[0] if by_category else None
    
    if top_category == 'transport':
        tips.append("Consider carpooling, using bus/train, or switching to e-bikes for short trips.")
    elif top_category == 'energy':
        tips.append("Switch to renewable energy providers and use energy-efficient appliances.")
    elif top_category == 'food':
        tips.append("Reduce meat consumption, especially beef, and choose local/seasonal produce.")
    
    if len(tips) == 0:
        tips.append("Keep tracking your emissions to identify reduction opportunities.")
    
    human_msg = f"📊 Summary: {total:.2f} kg CO₂e total"
    if start_date or end_date:
        human_msg += f" from {start_date or 'beginning'} to {end_date or 'now'}"
    human_msg += ". Top category: " + (top_category or 'none') + ".\n\n" + "\n".join(summary_parts)
    
    return {
        'success': True,
        'human_message': human_msg,
        'data': {
            'total_emissions_kg': total,
            'by_category': by_category,
            'category_shares': category_shares,
            'detailed_breakdown': detailed,
            'top_3_contributors': [{'subcategory': k, 'kg': round(v, 2)} for k, v in top3_contributors],
            'tips': tips,
            'chart_ready': history['data']['chart_ready']
        }
    }


def generateTasks(user_id: Optional[str] = None, start_date: Optional[str] = None,
                  end_date: Optional[str] = None) -> Dict:
    """Generate personalized tasks/challenges based on user's history to reduce carbon footprint."""
    history = getHistory(user_id, start_date, end_date, detailed=True)
    
    entries = history['data']['entries']
    detailed = history['data']['detailed_breakdown']
    by_category = history['data']['by_category']
    
    tasks = []
    
    # Transport tasks
    if detailed.get('transport') and detailed['transport'].get('vehicles'):
        transport = detailed['transport']
        car_data = next((v for v in transport['vehicles'] if v['vehicle'] == 'car'), None)
        
        if car_data and car_data['total_km'] > 50:
            tasks.append({
                'id': 'task_transport_car_reduce',
                'category': 'transport',
                'title': 'Reduce Car Travel by 20%',
                'description': f"You've traveled {car_data['total_km']:.1f} km by car. Try carpooling, using public transport, or cycling for short trips.",
                'impact': f"Potential reduction: ~{(car_data['total_emissions_kg'] * 0.2):.2f} kg CO₂e",
                'difficulty': 'medium',
                'estimated_savings_kg': round(car_data['total_emissions_kg'] * 0.2, 2)
            })
        
        if car_data and car_data['total_km'] > 100:
            tasks.append({
                'id': 'task_transport_public',
                'category': 'transport',
                'title': 'Switch to Public Transport',
                'description': 'Try using bus or train for your daily commute. It can reduce emissions by 50-70% compared to cars.',
                'impact': f"Potential reduction: ~{(car_data['total_emissions_kg'] * 0.6):.2f} kg CO₂e",
                'difficulty': 'easy',
                'estimated_savings_kg': round(car_data['total_emissions_kg'] * 0.6, 2)
            })
        
        bus_data = next((v for v in transport['vehicles'] if v['vehicle'] == 'bus'), None)
        if not bus_data or bus_data['total_km'] < car_data['total_km'] * 0.3 if car_data else False:
            tasks.append({
                'id': 'task_transport_bus',
                'category': 'transport',
                'title': 'Use Bus for Short Trips',
                'description': 'Try taking the bus for trips under 5 km. Buses are much more efficient per passenger.',
                'impact': 'Potential reduction: ~2-5 kg CO₂e per month',
                'difficulty': 'easy',
                'estimated_savings_kg': 3.0
            })
        
        # Bicycle/walking tasks
        bike_data = next((v for v in transport['vehicles'] if v['vehicle'] in ['bicycle', 'bike']), None)
        if not bike_data or bike_data['total_km'] < 10:
            tasks.append({
                'id': 'task_transport_bike',
                'category': 'transport',
                'title': 'Cycle or Walk for Short Distances',
                'description': 'For trips under 3 km, consider cycling or walking. Zero emissions and great for health!',
                'impact': 'Potential reduction: ~1-3 kg CO₂e per month',
                'difficulty': 'easy',
                'estimated_savings_kg': 2.0
            })
    
    # Shopping tasks
    if detailed.get('shopping') and detailed['shopping'].get('items'):
        shopping = detailed['shopping']
        tasks.append({
            'id': 'task_shopping_bag',
            'category': 'shopping',
            'title': 'Carry Reusable Shopping Bags',
            'description': 'Bring your own reusable bags when shopping. Plastic bags contribute to waste emissions.',
            'impact': 'Potential reduction: ~0.5-1 kg CO₂e per month',
            'difficulty': 'easy',
            'estimated_savings_kg': 0.75
        })
        
        tasks.append({
            'id': 'task_shopping_bulk',
            'category': 'shopping',
            'title': 'Buy in Bulk to Reduce Packaging',
            'description': 'Purchase items in larger quantities to reduce packaging waste and trips to the store.',
            'impact': 'Potential reduction: ~1-2 kg CO₂e per month',
            'difficulty': 'easy',
            'estimated_savings_kg': 1.5
        })
        
        tasks.append({
            'id': 'task_shopping_local',
            'category': 'shopping',
            'title': 'Buy Local and Seasonal Products',
            'description': 'Choose locally produced items to reduce transportation emissions from shipping.',
            'impact': 'Potential reduction: ~2-4 kg CO₂e per month',
            'difficulty': 'medium',
            'estimated_savings_kg': 3.0
        })
        
        tasks.append({
            'id': 'task_shopping_secondhand',
            'category': 'shopping',
            'title': 'Buy Secondhand or Refurbished Items',
            'description': 'Consider buying secondhand clothing, electronics, or furniture. Reduces manufacturing emissions.',
            'impact': 'Potential reduction: ~5-10 kg CO₂e per item',
            'difficulty': 'medium',
            'estimated_savings_kg': 7.5
        })
    
    # Food tasks
    if detailed.get('food') and detailed['food'].get('items'):
        food = detailed['food']
        meat_items = [item for item in food['items'] if 'meat' in item['item'].lower() or 'beef' in item['item'].lower() or 'chicken' in item['item'].lower()]
        
        if meat_items:
            total_meat_emissions = sum(item['total_emissions_kg'] for item in meat_items)
            tasks.append({
                'id': 'task_food_reduce_meat',
                'category': 'food',
                'title': 'Reduce Meat Consumption',
                'description': f"You consume {sum(item['total_amount'] for item in meat_items):.1f} servings of meat. Try having 2-3 meat-free days per week.",
                'impact': f"Potential reduction: ~{(total_meat_emissions * 0.3):.2f} kg CO₂e per month",
                'difficulty': 'medium',
                'estimated_savings_kg': round(total_meat_emissions * 0.3, 2)
            })
            
            tasks.append({
                'id': 'task_food_plant_based',
                'category': 'food',
                'title': 'Try Plant-Based Alternatives',
                'description': 'Replace one meat meal per week with plant-based options. Beans, lentils, and tofu have much lower emissions.',
                'impact': f"Potential reduction: ~{(total_meat_emissions * 0.15):.2f} kg CO₂e per month",
                'difficulty': 'easy',
                'estimated_savings_kg': round(total_meat_emissions * 0.15, 2)
            })
        
        tasks.append({
            'id': 'task_food_waste',
            'category': 'food',
            'title': 'Reduce Food Waste',
            'description': 'Plan meals, use leftovers, and compost food scraps. Food waste contributes significantly to emissions.',
            'impact': 'Potential reduction: ~3-5 kg CO₂e per month',
            'difficulty': 'medium',
            'estimated_savings_kg': 4.0
        })
        
        tasks.append({
            'id': 'task_food_local',
            'category': 'food',
            'title': 'Buy Local and Seasonal Produce',
            'description': 'Choose locally grown, seasonal fruits and vegetables to reduce transportation emissions.',
            'impact': 'Potential reduction: ~1-2 kg CO₂e per month',
            'difficulty': 'easy',
            'estimated_savings_kg': 1.5
        })
    
    # Energy tasks
    if by_category.get('energy', 0) > 0:
        tasks.append({
            'id': 'task_energy_switch',
            'category': 'energy',
            'title': 'Switch to Renewable Energy',
            'description': 'Switch to a renewable energy provider or install solar panels if possible.',
            'impact': f"Potential reduction: ~{(by_category['energy'] * 0.5):.2f} kg CO₂e",
            'difficulty': 'hard',
            'estimated_savings_kg': round(by_category['energy'] * 0.5, 2)
        })
        
        tasks.append({
            'id': 'task_energy_efficient',
            'category': 'energy',
            'title': 'Use Energy-Efficient Appliances',
            'description': 'Replace old appliances with energy-efficient models and use LED bulbs.',
            'impact': 'Potential reduction: ~2-4 kg CO₂e per month',
            'difficulty': 'medium',
            'estimated_savings_kg': 3.0
        })
        
        tasks.append({
            'id': 'task_energy_unplug',
            'category': 'energy',
            'title': 'Unplug Electronics When Not in Use',
            'description': 'Turn off and unplug devices when not in use to reduce phantom power consumption.',
            'impact': 'Potential reduction: ~1-2 kg CO₂e per month',
            'difficulty': 'easy',
            'estimated_savings_kg': 1.5
        })
    
    # General tasks
    tasks.append({
        'id': 'task_general_track',
        'category': 'general',
        'title': 'Continue Tracking Your Carbon Footprint',
        'description': 'Keep logging your activities to monitor progress and identify new reduction opportunities.',
        'impact': 'Helps identify patterns and areas for improvement',
        'difficulty': 'easy',
        'estimated_savings_kg': 0
    })
    
    # Sort by estimated savings (highest first)
    tasks.sort(key=lambda x: x.get('estimated_savings_kg', 0), reverse=True)
    
    # Limit to top 10 tasks
    tasks = tasks[:10]
    
    total_potential_savings = sum(t.get('estimated_savings_kg', 0) for t in tasks)
    
    human_msg = f"📋 Generated {len(tasks)} personalized tasks to reduce your carbon footprint!\n\n"
    human_msg += f"💡 Potential total reduction: {total_potential_savings:.2f} kg CO₂e\n\n"
    human_msg += "Top recommendations:\n"
    for i, task in enumerate(tasks[:3], 1):
        human_msg += f"{i}. {task['title']} - {task['impact']}\n"
    
    return {
        'success': True,
        'human_message': human_msg,
        'data': {
            'tasks': tasks,
            'total_tasks': len(tasks),
            'total_potential_savings_kg': round(total_potential_savings, 2),
            'by_category': {
                cat: [t for t in tasks if t['category'] == cat]
                for cat in ['transport', 'food', 'shopping', 'energy', 'general']
            }
        }
    }


# API Endpoints

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'service': 'CarbonBuddy',
        'mock_mode': MOCK_MODE,
    })


@app.route('/api/logEntry', methods=['POST'])
def api_log_entry():
    """Log an entry endpoint."""
    try:
        data = request.json
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        result = logEntry(data, user_id)
        return jsonify(result), 200 if result['success'] else 400
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error logging entry: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/getHistory', methods=['GET', 'POST'])
def api_get_history():
    """Get history endpoint."""
    try:
        if request.method == 'POST':
            data = request.json
        else:
            data = request.args.to_dict()
        
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        city = data.get('city')
        category = data.get('category')
        
        result = getHistory(user_id, start_date, end_date, city, category)
        
        # If raw JSON requested
        if data.get('raw_json') == 'true':
            return jsonify(result['data']), 200
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error retrieving history: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/comparePeriods', methods=['POST'])
def api_compare_periods():
    """Compare periods endpoint."""
    try:
        data = request.json
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        
        result = comparePeriods(
            user_id,
            data.get('from_start'),
            data.get('from_end'),
            data.get('to_start'),
            data.get('to_end'),
            data.get('category')
        )
        
        if data.get('raw_json') == 'true':
            return jsonify(result['data'] if 'data' in result else result), 200
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error comparing periods: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/compareCities', methods=['POST'])
def api_compare_cities():
    """Compare cities endpoint."""
    try:
        data = request.json
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        
        result = compareCities(
            user_id,
            data.get('cityA'),
            data.get('cityB'),
            data.get('start_date'),
            data.get('end_date'),
            data.get('category')
        )
        
        if data.get('raw_json') == 'true':
            return jsonify(result['data']), 200
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error comparing cities: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/summary', methods=['GET', 'POST'])
def api_summary():
    """Summary endpoint."""
    try:
        if request.method == 'POST':
            data = request.json
        else:
            data = request.args.to_dict()
        
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        result = summary(user_id, start_date, end_date)
        
        if data.get('raw_json') == 'true':
            return jsonify(result['data']), 200
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error generating summary: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/getTasks', methods=['GET', 'POST'])
def api_get_tasks():
    """Get personalized tasks/challenges endpoint."""
    try:
        if request.method == 'POST':
            data = request.json
        else:
            data = request.args.to_dict()
        
        user_id = data.get('user_id') or request.headers.get('X-User-Id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        result = generateTasks(user_id, start_date, end_date)
        
        if data.get('raw_json') == 'true':
            return jsonify(result['data']), 200
        
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error generating tasks: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/api/getEmissionFactors', methods=['GET'])
def api_get_emission_factors():
    """Get all emission factors."""
    return jsonify({
        'success': True,
        'data': {
            'factors': emission_factors_db,
            'units': 'kg CO₂e per km'
        }
    }), 200


@app.route('/api/setEmissionFactor', methods=['POST'])
def api_set_emission_factor():
    """Set an emission factor."""
    try:
        data = request.json
        subcategory = data.get('subcategory')
        value = data.get('value')
        
        if not subcategory or value is None:
            return jsonify({
                'success': False,
                'human_message': 'Error: subcategory and value are required.',
                'data': {'error': 'Missing parameters'}
            }), 400
        
        emission_factors_db[subcategory.lower()] = float(value)
        
        return jsonify({
            'success': True,
            'human_message': f'Emission factor for {subcategory} set to {value} kg CO₂e per km.',
            'data': {'subcategory': subcategory, 'value': value}
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'human_message': f'Error setting emission factor: {str(e)}',
            'data': {'error': str(e)}
        }), 500


@app.route('/chatbot/chat', methods=['POST'])
def chat():
    """Main chatbot endpoint - routes to CarbonBuddy functions."""
    try:
        data = request.json
        message = data.get('message', '').strip()
        user_id = data.get('userId') or data.get('user_id')
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        message_lower = message.lower()
        
        # Detect intent and route
        if any(phrase in message_lower for phrase in ['log', 'add', 'i rode', 'i took', 'i drove', 'i traveled']):
            # Log entry
            result = logEntry({'message': message}, user_id)
            return jsonify({
                'text': result['human_message'],
                'data': result['data'],
                'intent': 'log_entry',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        elif any(phrase in message_lower for phrase in ['history', 'show', 'list', 'entries']):
            # Get history
            # Try to extract date range
            start_date = None
            end_date = None
            if 'october 2025' in message_lower or 'oct 2025' in message_lower:
                start_date = '2025-10-01'
                end_date = '2025-10-31'
            elif 'september 2025' in message_lower or 'sep 2025' in message_lower:
                start_date = '2025-09-01'
                end_date = '2025-09-30'
            elif 'this month' in message_lower:
                now = datetime.now()
                start_date = now.replace(day=1).strftime('%Y-%m-%d')
                end_date = now.strftime('%Y-%m-%d')
            elif 'last month' in message_lower:
                now = datetime.now()
                last_month = now.replace(day=1) - timedelta(days=1)
                start_date = last_month.replace(day=1).strftime('%Y-%m-%d')
                end_date = last_month.strftime('%Y-%m-%d')
            
            result = getHistory(user_id, start_date, end_date)
            return jsonify({
                'text': result['human_message'],
                'data': result['data'],
                'intent': 'get_history',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        elif 'compare' in message_lower and ('month' in message_lower or 'period' in message_lower):
            # Compare periods
            now = datetime.now()
            this_month_start = now.replace(day=1).strftime('%Y-%m-%d')
            this_month_end = now.strftime('%Y-%m-%d')
            last_month = now.replace(day=1) - timedelta(days=1)
            last_month_start = last_month.replace(day=1).strftime('%Y-%m-%d')
            last_month_end = last_month.strftime('%Y-%m-%d')
            
            result = comparePeriods(user_id, last_month_start, last_month_end, this_month_start, this_month_end)
            return jsonify({
                'text': result['human_message'],
                'data': result,
                'intent': 'compare_periods',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        elif 'compare' in message_lower and ('delhi' in message_lower or 'bengaluru' in message_lower or 'bangalore' in message_lower):
            # Compare cities
            cityA = 'Delhi' if 'delhi' in message_lower else 'Bengaluru'
            cityB = 'Bengaluru' if cityA == 'Delhi' else 'Delhi'
            
            # Extract date range
            start_date = '2025-09-01'
            end_date = '2025-09-30'
            if 'september 2025' in message_lower:
                start_date = '2025-09-01'
                end_date = '2025-09-30'
            
            result = compareCities(user_id, cityA, cityB, start_date, end_date)
            return jsonify({
                'text': result['human_message'],
                'data': result['data'],
                'intent': 'compare_cities',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        elif any(phrase in message_lower for phrase in ['summary', 'overview', 'total', 'this year']):
            # Summary
            start_date = None
            end_date = None
            if 'this year' in message_lower:
                now = datetime.now()
                start_date = now.replace(month=1, day=1).strftime('%Y-%m-%d')
                end_date = now.strftime('%Y-%m-%d')
            
            result = summary(user_id, start_date, end_date)
            return jsonify({
                'text': result['human_message'],
                'data': result['data'],
                'intent': 'summary',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        elif any(phrase in message_lower for phrase in ['tasks', 'challenges', 'suggestions', 'tips', 'how to reduce', 'reduce carbon']):
            # Generate tasks
            start_date = None
            end_date = None
            if 'this month' in message_lower:
                now = datetime.now()
                start_date = now.replace(day=1).strftime('%Y-%m-%d')
                end_date = now.strftime('%Y-%m-%d')
            elif 'last month' in message_lower:
                now = datetime.now()
                last_month = now.replace(day=1) - timedelta(days=1)
                start_date = last_month.replace(day=1).strftime('%Y-%m-%d')
                end_date = last_month.strftime('%Y-%m-%d')
            
            result = generateTasks(user_id, start_date, end_date)
            return jsonify({
                'text': result['human_message'],
                'data': result['data'],
                'intent': 'get_tasks',
                'timestamp': datetime.utcnow().isoformat()
            }), 200
        
        else:
            # Default response
            return jsonify({
                'text': "I'm CarbonBuddy! I can help you:\n• Log activities (e.g., 'I rode a car 12.5 km today in Delhi')\n• Show history (e.g., 'Show my history for October 2025')\n• Compare periods (e.g., 'Compare last month with this month')\n• Compare cities (e.g., 'Compare Delhi and Bengaluru')\n• Get summaries (e.g., 'Give me a summary of all usage this year')",
                'intent': 'general_inquiry',
                'quick_replies': ['Log Activity', 'Show History', 'Compare Periods', 'Get Summary'],
                'timestamp': datetime.utcnow().isoformat()
            }), 200
    
    except Exception as e:
        print(f"Chat endpoint error: {e}")
        return jsonify({
            'error': 'An error occurred processing your message',
            'text': f"I'm sorry, I encountered an error: {str(e)}"
        }), 500


# Serve static files (must be last route)
@app.route('/<path:filename>')
def serve_static_files(filename):
    if filename.startswith(('api/', 'chatbot/', 'health')):
        return jsonify({'error': 'Not found'}), 404
    
    if filename.endswith(('.js', '.css', '.json', '.png', '.jpg', '.svg', '.ico')):
        try:
            file_path = os.path.join(BASE_DIR, filename)
            if os.path.exists(file_path):
                return send_file(file_path)
        except Exception as e:
            print(f"Error serving file {filename}: {e}")
    
    return jsonify({'error': 'File not found'}), 404


@app.route('/')
def serve_index():
    """Serve index.html from root."""
    index_path = os.path.join(BASE_DIR, 'index.html')
    if os.path.exists(index_path):
        return send_file(index_path)
    return jsonify({
        'message': 'CarbonBuddy API',
        'status': 'running',
        'endpoints': {
            'logEntry': '/api/logEntry',
            'getHistory': '/api/getHistory',
            'comparePeriods': '/api/comparePeriods',
            'compareCities': '/api/compareCities',
            'summary': '/api/summary',
            'getEmissionFactors': '/api/getEmissionFactors',
            'setEmissionFactor': '/api/setEmissionFactor',
            'chatbot': '/chatbot/chat',
            'getTasks': '/api/getTasks'
        }
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'false').lower() == 'true'
    
    print(f"""
    CarbonBuddy API
    ===============
    Running on: http://localhost:{port}
    Mock Mode: {MOCK_MODE}
    
    Endpoints:
    - POST /api/logEntry - Log an activity entry
    - GET/POST /api/getHistory - Get history with detailed breakdowns
    - POST /api/comparePeriods - Compare two time periods
    - POST /api/compareCities - Compare two cities
    - GET/POST /api/summary - Get comprehensive summary with detailed breakdowns
    - GET/POST /api/getTasks - Get personalized tasks to reduce carbon footprint
    - GET /api/getEmissionFactors - Get all emission factors
    - POST /api/setEmissionFactor - Set an emission factor
    - POST /chatbot/chat - Main chat endpoint (routes to functions)
    """)
    
    app.run(host='0.0.0.0', port=port, debug=debug)
