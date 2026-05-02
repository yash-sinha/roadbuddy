import os

POLICY_TEXT = """
CLAIMBUDDY MOTOR INSURANCE — ROADSIDE ASSISTANCE POLICY
Policy Reference: CBM-RA-2024 | Effective Date: 1 January 2024

SECTION 1 — COVERAGE OVERVIEW

ClaimBuddy Motor Insurance provides 24-hour roadside assistance to all policyholders with an active comprehensive or roadside-plus plan. Coverage is available throughout the United Kingdom and applies to the insured vehicle as listed on the policy schedule.

SECTION 2 — COVERED EVENTS

2.1 Engine Failure
Coverage applies when the insured vehicle sustains a mechanical breakdown of the engine or drivetrain that renders the vehicle unable to be driven safely. This includes sudden seizure, overheating leading to non-operation, timing belt or chain failure, and cooling system failures. ClaimBuddy will dispatch a tow truck to transport the vehicle to the nearest authorised repair facility. Towing distance is covered up to 50 miles from the breakdown location.

2.2 Flat Tyre
Coverage applies to tyre punctures, blowouts, and deflation events that prevent safe vehicle operation. If a road-worthy spare tyre is present, a repair technician will be dispatched to fit the spare at the roadside. If no spare is available or the spare is unroadworthy, the vehicle will be towed to the nearest tyre fitting centre. Tyre replacement costs are not covered; only labour and transportation are included.

2.3 Accident Damage
Coverage applies following a road traffic accident that has rendered the insured vehicle immobile or unsafe to drive. ClaimBuddy will arrange towing from the incident scene to the nearest authorised bodywork or mechanical repair facility. Administrative items such as an incident reference number or police report may be requested by the claims handler after dispatch but are not required to authorise initial roadside assistance.

2.4 Battery and Electrical Failure
Coverage applies when the vehicle battery is fully discharged, faulty, or when an electrical fault prevents engine start. ClaimBuddy dispatches a repair technician to attempt a jump-start or battery replacement at the roadside. If the vehicle cannot be started after reasonable attempts, it will be towed to an authorised garage.

SECTION 3 — EXCLUSIONS

The following events and circumstances are expressly excluded from coverage under this policy:

3.1 Cosmetic Damage
Scratches, dents, paint chips, or any damage that is purely cosmetic and does not affect the safe operation of the vehicle are not covered. Cosmetic damage claims will be declined at the assessment stage.

3.2 Racing and Competition Events
Any breakdown or incident occurring during a motorsport event, race, rally, track day, or any organised speed or performance competition is excluded from coverage regardless of the nature of the damage.

3.3 Drink or Drug Driving Incidents
Any incident in which the policyholder is found to have been operating the vehicle under the influence of alcohol or controlled substances will result in immediate denial of the claim. ClaimBuddy reserves the right to recover any costs incurred prior to determination of such circumstances.

3.4 Deliberate Damage
Damage caused intentionally by the policyholder or any authorised driver is excluded.

3.5 Unregistered or Uninsured Vehicles
Coverage only applies to the vehicle listed on the policy schedule. Vehicles that are not registered to the policyholder or that have a lapsed policy are not covered.

SECTION 4 — CLAIM PROCEDURE

To initiate a claim, the policyholder must contact ClaimBuddy Assistance via the dedicated claims line or digital channel. The policyholder must provide: full name, policy number, current location, vehicle registration, and a description of the incident. Once all required information is collected, ClaimBuddy will assess coverage, classify the type of assistance required, and dispatch the appropriate service.

SECTION 5 — SERVICE STANDARDS

ClaimBuddy targets a response time of under 45 minutes for urban areas and under 90 minutes for rural locations. All dispatched technicians are certified and operate under ClaimBuddy-approved safety standards. In cases where coverage confidence is below the required threshold, a senior claims handler will be consulted before any service is dispatched.

SECTION 6 — APPEALS

If a claim is declined, the policyholder may submit a formal appeal within 28 days. Appeals must include supporting documentation such as photographs, police reports, or third-party statements.
""".strip()

GARAGES = [
    {"name": "Central Auto Recovery", "lat": 51.5155, "lng": -0.0922, "speciality": "both"},
    {"name": "City Tow Services", "lat": 51.5074, "lng": -0.1278, "speciality": "tow"},
    {"name": "East End Repairs", "lat": 51.5203, "lng": -0.0524, "speciality": "repair"},
    {"name": "South Bank Garage", "lat": 51.5045, "lng": -0.1132, "speciality": "both"},
    {"name": "Canary Wharf Motors", "lat": 51.5054, "lng": -0.0235, "speciality": "repair"},
]

POSTCODE_LOOKUP: dict[str, tuple[float, float]] = {
    "SW1A 1AA": (51.5014, -0.1419),
    "EC1A 1BB": (51.5177, -0.1018),
    "W1A 1AA": (51.5186, -0.1444),
    "SE1 7PB": (51.5046, -0.0902),
    "E1 6RF": (51.5156, -0.0714),
    "N1 9GU": (51.5362, -0.1031),
    "WC2N 5DU": (51.5084, -0.1246),
    "SW7 2AZ": (51.4984, -0.1775),
    "E14 5AB": (51.5054, -0.0235),
    "NW1 6XE": (51.5286, -0.1437),
}


def generate_policy(path: str = "policy.txt") -> None:
    with open(path, "w") as f:
        f.write(POLICY_TEXT)
