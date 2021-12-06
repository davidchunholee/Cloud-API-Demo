from collections import OrderedDict
from flask import Flask, request, jsonify, render_template, redirect
from google.cloud import datastore
from google.oauth2 import id_token
import constants
import google.auth.transport
import random
import requests

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False
client = datastore.Client()


@app.route('/')
def index():
    # Initial welcome page - has html button on page to reroute to /signin
    return render_template("welcome.html")


@app.route('/signin')
def signin():
    # Random possible letter/numbers for creating state
    char_list = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l',
                 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x',
                 'y', 'z',
                 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L',
                 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X',
                 'Y', 'Z']

    # Create and append string of 20 random letter/numbers to use as the random state generated
    random_state = ''
    for i in range(20):
        random_num = random.randint(0, len(char_list) - 1)
        random_state = random_state + char_list[random_num]

    # Store newly created state as an entity on datastore
    new_state = datastore.entity.Entity(key=client.key(constants.STATES))
    new_state.update({"state_value": random_state})
    client.put(new_state)

    # Generate string sent to Google OAuth endpoint with required information
    auth_uri = 'https://accounts.google.com/o/oauth2/v2/auth?response_type=code''&client_id={}&redirect_uri={}&scope={}&state={}'.format(
            constants.CLIENT_ID,
            constants.REDIRECT_URI,
            constants.SCOPE,
            random_state
        )
    return redirect(auth_uri)


@app.route('/oauth')
def oauth():
    # If redirected, we successfully received access code from Google after user gives consent
    auth_state = request.args.get('state')
    auth_code = request.args.get('code')

    # Query through datastore to make sure it matches one of the states to validate request
    query = client.query(kind=constants.STATES)
    results = list(query.fetch())
    foundMatch = False
    for result in results:
        if result["state_value"] == auth_state:
            foundMatch = True
            break

    # State not found and does not match in datastore
    if not foundMatch:
        return render_template('failed.html')

    # Client has verified - now send post request with access code so Google can verify client and obtain token
    if foundMatch:
        data = {'code': auth_code,
                'client_id': constants.CLIENT_ID,
                'client_secret': constants.CLIENT_SECRET,
                'redirect_uri': constants.REDIRECT_URI,
                'grant_type': 'authorization_code'}
        r = requests.post('https://oauth2.googleapis.com/token', data=data)

        jwt = r.json().get('id_token')

        try:
            id_info = id_token.verify_oauth2_token(jwt,
                                                   google.auth.transport.requests.Request(),
                                                   constants.CLIENT_ID)

            # ID token is valid. Get the user's Google Account ID from the decoded token.
            user_id = id_info['sub']
            first_name = id_info['given_name']
            last_name = id_info['family_name']

            user_query = client.query(kind=constants.USERS)
            user_results = list(user_query.fetch())
            user_found = False

            # Search for pre-existing user_id
            for user_result in user_results:
                if user_result["user_id"] == user_id:
                    user_found = True

            if not user_found:
                new_user = datastore.entity.Entity(
                    key=client.key(constants.USERS))
                new_user.update(
                    {
                        "user_id": user_id,
                        "first_name": first_name,
                        "last_name": last_name
                    }
                )
                client.put(new_user)

            return render_template("userinfo.html", user_id=user_id,
                                   first_name=first_name,
                                   last_name=last_name, jwt=jwt)

        except (ValueError, TypeError, AttributeError):
            # Invalid token
            return render_template('failed.html')


@app.route('/users', methods=['GET'])
def users_get():
    """
    Method to retrieve all users
    ------------------------------------------------------------------------------------------
    RETRIEVE all boats: Submits GET request with no path parameters and no body in JSON format
        Returns: JSON response
            Success Status: 200 OK (users listed)
    """
    if request.method == 'GET':
        query = client.query(kind=constants.USERS)
        results = list(query.fetch())
        all_users = []
        count = 0

        for result in results:
            count += 1
            formatted = format_user(result)
            all_users.append(formatted)

        return_users = {"Showing " + str(count) + " users": all_users}

        return jsonify(return_users)


@app.route('/boats', methods=['POST', 'GET'])
def boats_get_post():
    """
    Method to retrieve boats or add a boat
    ------------------------------------------------------------------------------------------
    RETRIEVE all boats for user: Submits GET request with no body in JSON format
        Returns: JSON response
            Success Status: 200 OK (boats listed)
                NOTE: If valid JWT provided, returns owned boats
            Failure Status:
                401 (Invalid or missing JWT provided)
                405 (Non-GET/POST request)
    ------------------------------------------------------------------------------------------
    CREATE a boat: Submits POST request with required body in JSON format
        JSON attributes:
            name (str) : name of boat - required
            type (str) : type of boat (Sailboat, Catamaran, etc) - required
            length (int) : length of boat (in feet) - required
        Returns: JSON response
            Success Status: 201 (boat created)
            Failure Status:
                            400 (missing part of 3 required attributes)
                            401 (missing or invalid JWT)
                            405 (Non-GET/POST request)
                            415 (content-type not set to "application/json")
    """
    # Retrieve a boat with pagination
    if request.method == 'GET':
        query = client.query(kind=constants.BOATS)
        curr_boats = []

        # Validate JWT
        try:
            received_jwt = request.headers.get('Authorization')
            if received_jwt is None:
                return ({
                            "Error": "Unauthorized: Missing JWT"
                        }, 401)

            else:
                # JWT supplied - parse token
                received_jwt = received_jwt.split()[1]

            # Specify the CLIENT_ID of the app that accesses the backend:
            id_info = id_token.verify_oauth2_token(received_jwt,
                                                   google.auth.transport.requests.Request(),
                                                   constants.CLIENT_ID)
            # ID token is valid. Get the user's Google Account ID from the decoded token.
            owner_id = id_info['sub']
            query.add_filter("owner", "=", id_info['sub'])

            results = list(query.fetch())
            total_count = len(results)

            # Setup pagination parameters (num of queries per page)
            q_limit = int(request.args.get("limit", "5"))
            q_offset = int(request.args.get("offset", "0"))
            l_iterator = query.fetch(limit=q_limit, offset=q_offset)
            pages = l_iterator.pages
            results = list(next(pages))

            # More entities exist than currently displayed; setup next_url
            if l_iterator.next_page_token:
                next_offset = q_offset + q_limit
                next_url = request.base_url + "?limit=" + str(
                    q_limit) + "&offset=" + str(next_offset)
            else:
                next_url = None

            # Search each boat's owner and retrieve matches
            for result in results:
                if result["owner"] == owner_id:
                    iter_boat = format_boat(result)
                    curr_boats.append(iter_boat)

            all_boats = {
                "boats": curr_boats,
                "Total boats": total_count
            }

            if next_url:
                all_boats["next"] = next_url

            return jsonify(all_boats)

        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "Unauthorized: Invalid JWT"
                    }, 401)

    # Create a boat
    elif request.method == 'POST':
        if request.content_type == "application/json":
            content = request.get_json()

            if len(content) != 3 or "name" not in content or "type" not in content or "length" not in content:
                return ({
                            "Error": "The request object is missing at least one of the required attributes"
                        }, 400)

            if type(content["length"]) != int:
                return ({
                            "Error": "Length must be an integer"
                        }, 400)

            if content["length"] < 0:
                return ({
                            "Error": "Length must be a positive integer"
                        }, 400)

            # Validate JWT
            try:
                received_jwt = request.headers.get('Authorization')
                if received_jwt is None:
                    return ({
                                "Error": "Unauthorized: Missing JWT"
                            }, 401)
                else:
                    received_jwt = received_jwt.split()[1]
                # Specify the CLIENT_ID of the app that accesses the backend:
                id_info = id_token.verify_oauth2_token(received_jwt,
                                                       google.auth.transport.requests.Request(),
                                                       constants.CLIENT_ID)

                # ID token is valid. Get the user's Google Account ID from the decoded token.
                owner_id = id_info['sub']

                # All required attributes given - proceed to create new_boat
                new_boat = datastore.entity.Entity(key=client.key(constants.BOATS))
                new_boat.update(
                    {
                        "name": content["name"],
                        "type": content["type"],
                        "length": content["length"],
                        "owner": owner_id,
                        "loads": []
                    }
                )
                client.put(new_boat)
                formatted = format_boat(new_boat)
                return jsonify(formatted), 201

            except (ValueError, TypeError, AttributeError):
                return ({
                            "Error": "Unauthorized: Invalid JWT"
                        }, 401)
        else:
            return ({
                        "Error": "Unsupported Media Type"
                    }, 415)


@app.route('/boats/<boat_id>', methods=['GET', 'PATCH', 'PUT', 'DELETE'])
def boat_specific(boat_id):
    """
    Method to retrieve or delete a specific boat
    ------------------------------------------------------------------------------------------
    RETRIEVE an existing boat: Submits GET request with boat_id and no body in JSON format
        Path Parameters:
            boat_id: ID of boat as <id>
        Returns: JSON response
            Success Status: 200 (boat retrieved)
            Failure Status:
                            401 (Invalid or missing JWT provided)
                            403 (Boat owned by someone else)
                            404 (Boat not found with particular boat_id)
                            406 (client does not accept application/json)
    ------------------------------------------------------------------------------------------
    EDIT an existing boat (PATCH): Submits PATCH request with boat_id and required body in JSON format
        Path Parameters:
            boat_id: ID of boat as <id>
        JSON attributes:
            name (str) : name of boat - required
            type (str) : type of boat (Sailboat, Catamaran, etc) - required
            length (int) : length of boat (in feet) - required
        Returns: JSON response
            Success Status: 200 (boat edited)
            Failure Status:
                            400 (Updating invalid attribute)
                            401 (Invalid or missing JWT provided)
                            403 (Boat owned by someone else)
                            404 (No boat with boat_id exists)
                            405 (Not acceptable method)
                            415 (content-type not set to "application/json")
    ------------------------------------------------------------------------------------------
    EDIT an existing boat (PUT): Submits PUT request with boat_id and required body in JSON format
        Path Parameters:
            boat_id: ID of boat as <id>
        JSON attributes:
            name (str) : name of boat - required
            type (str) : type of boat (Sailboat, Catamaran, etc) - required
            length (int) : length of boat (in feet) - required
        Returns: JSON response
            Success Status: 200 (boat edited)
            Failure Status:
                            400 (Missing 3 required attributes)
                            401 (Invalid or missing JWT provided)
                            403 (Boat owned by someone else)
                            404 (No boat with boat_id exists)
                            405 (Unsupported method)
                            415 (content-type not set to "application/json")
    ------------------------------------------------------------------------------------------
    DELETE an existing boat: Submits DELETE request with boat_id and no body in JSON format
        Path Parameters:
            boat_id: ID of boat as <id>
        Returns: 
            Success Status: 204 (No Body returned)
            Failure Status: JSON Body with failure message returned
                            401 (Invalid or missing JWT provided)
                            403 (Boat owned by someone else)
                            404 (Boat not found with particular boat_id)
                            405 (Unsupported method)
    """
    if request.method == 'GET':
        if 'application/json' in request.accept_mimetypes:
            try:
                boat_key = client.key(constants.BOATS, int(boat_id))
                boat = client.get(key=boat_key)

                received_jwt = request.headers.get('Authorization')
                if received_jwt is None:
                    return ({
                                "Error": "Unauthorized: Missing JWT"
                            }, 401)

                elif boat is None:
                    return ({
                                "Error": "No boat with this boat_id exists"
                            }, 404)

                else:
                    received_jwt = received_jwt.split()[1]

                # Specify the CLIENT_ID of the app that accesses the backend:
                id_info = id_token.verify_oauth2_token(received_jwt,
                                                       google.auth.transport.requests.Request(),
                                                       constants.CLIENT_ID)

                # ID token is valid. Get the user's Google Account ID from the decoded token.
                owner_id = id_info['sub']

                if boat["owner"] == owner_id:
                    formatted = format_boat(boat)
                    return jsonify(formatted)

                return ({
                            "Error": "Forbidden: Boat owned by someone else"
                        }, 403)

            except (ValueError, TypeError, AttributeError):
                return ({
                            "Error": "Unauthorized: Invalid JWT"
                        }, 401)
        else:
            return ({
                        "Error": "Client must accept application/json"
                    }, 406)

    # Edit subset of a specific boat's attributes
    elif request.method == 'PATCH':
        if request.content_type == "application/json":
            content = request.get_json()

            try:
                boat_key = client.key(constants.BOATS, int(boat_id))
                boat = client.get(key=boat_key)

                received_jwt = request.headers.get('Authorization')
                if received_jwt is None:
                    return ({
                                "Error": "Unauthorized: Missing JWT"
                            }, 401)

                elif boat is None:
                    return ({
                                "Error": "No boat with this boat_id exists"
                            }, 404)

                else:
                    received_jwt = received_jwt.split()[1]

                # Specify the CLIENT_ID of the app that accesses the backend:
                id_info = id_token.verify_oauth2_token(received_jwt,
                                                       google.auth.transport.requests.Request(),
                                                       constants.CLIENT_ID)
                # ID token is valid. Get the user's Google Account ID from the decoded token.
                owner_id = id_info['sub']

                allowed_changes = ["name", "type", "length"]
                for attribute in content:
                    if attribute not in allowed_changes:
                        return ({
                                    "Error": "Updating invalid attribute"
                                }, 400)

                if "name" in content:
                    if owner_id == boat["owner"]:
                        boat.update({
                            "name": content["name"]
                        })
                        client.put(boat)
                    else:
                        return ({
                                    "Error": "Forbidden: Boat owned by someone else"
                                }, 403)

                if "type" in content:
                    if owner_id == boat["owner"]:
                        boat.update({
                            "type": content["type"]
                        })
                        client.put(boat)
                    else:
                        return ({
                                    "Error": "Forbidden: Boat owned by someone else"
                                }, 403)

                if "length" in content:
                    if type(content["length"]) != int:
                        return ({
                                    "Error": "Length must be an integer"
                                }, 400)

                    if content["length"] < 0:
                        return ({
                                    "Error": "Length must be a positive integer"
                                }, 400)

                    if owner_id == boat["owner"]:
                        boat.update({
                            "length": content["length"]
                        })
                        client.put(boat)
                    else:
                        return ({
                                    "Error": "Forbidden: Boat owned by someone else"
                                }, 403)

                formatted = format_boat(boat)
                return jsonify(formatted), 200

            except (ValueError, TypeError, AttributeError):
                return ({
                            "Error": "Unauthorized: Invalid JWT"
                        }, 401)
        else:
            return ({
                        "Error": "Unsupported Media Type"
                    }, 415)

    # Edit all of a boat's attributes
    elif request.method == 'PUT':
        if request.content_type == "application/json":
            content = request.get_json()

            try:
                boat_key = client.key(constants.BOATS, int(boat_id))
                boat = client.get(key=boat_key)

                received_jwt = request.headers.get('Authorization')
                if received_jwt is None:
                    return ({
                                "Error": "Unauthorized: Missing JWT"
                            }, 401)

                elif boat is None:
                    return ({
                                "Error": "No boat with this boat_id exists"
                            }, 404)

                else:
                    received_jwt = received_jwt.split()[1]

                # Specify the CLIENT_ID of the app that accesses the backend:
                id_info = id_token.verify_oauth2_token(received_jwt,
                                                       google.auth.transport.requests.Request(),
                                                       constants.CLIENT_ID)
                # ID token is valid. Get the user's Google Account ID from the decoded token.
                owner_id = id_info['sub']

                if len(content) != 3 or "name" not in content or "type" not in content or "length" not in content:
                    return ({
                                "Error": "The request object is missing at least one of the required attributes"
                            }, 400)

                if type(content["length"]) != int:
                    return ({
                                "Error": "Length must be an integer"
                            }, 400)

                if content["length"] < 0:
                    return ({
                                "Error": "Length must be a positive integer"
                            }, 400)

                if owner_id == boat["owner"]:
                    boat.update(
                        {
                            "name": content["name"],
                            "type": content["type"],
                            "length": content["length"]
                        }
                    )
                    client.put(boat)
                    formatted = format_boat(boat)
                    return formatted

                return ({
                            "Error": "Forbidden: Boat owned by someone else"
                        }, 403)

            except (ValueError, TypeError, AttributeError):
                return ({
                            "Error": "Unauthorized: Invalid JWT"
                        }, 401)
        else:
            return ({
                        "Error": "Unsupported Media Type"
                    }, 415)

    elif request.method == 'DELETE':
        try:
            boat_key = client.key(constants.BOATS, int(boat_id))
            boat = client.get(key=boat_key)
            # Datastore's deleting non-existing Entity does not return an error
            if boat is None:
                return ({
                            "Error": "No boat with this boat_id exists"
                        }, 404)

            received_jwt = request.headers.get('Authorization')
            if received_jwt is None:
                return ({
                            "Error": "Unauthorized: Missing JWT"
                        }, 401)
            else:
                received_jwt = received_jwt.split()[1]

            # Specify the CLIENT_ID of the app that accesses the backend:
            id_info = id_token.verify_oauth2_token(received_jwt,
                                                   google.auth.transport.requests.Request(),
                                                   constants.CLIENT_ID)

            # ID token is valid. Get the user's Google Account ID from the decoded token.
            owner_id = id_info['sub']

            if owner_id == boat["owner"]:
                # Check all loads and delete from loads if found
                query = client.query(kind=constants.LOADS)
                results = list(query.fetch())

                for result in results:
                    # Skip if it does not exist
                    if result["carrier"] is None:
                        continue
                    elif result["carrier"]["id"] == int(boat_id):
                        result.update(
                            {
                                "content": result["content"],
                                "volume": result["volume"],
                                "price": result["price"],
                                "carrier": None
                            }
                        )
                        client.put(result)
                client.delete(boat_key)
                return '', 204

            # Not owned by jwt holder
            else:
                return ({
                            "Error": "Forbidden: Boat owned by someone else"
                        }, 403)

        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "Unauthorized: Invalid JWT"
                    }, 401)


@app.route('/loads', methods=['POST', 'GET'])
def loads_get_post():
    """
    Method to retrieve all loads or add a load
    ------------------------------------------------------------------------------------------
    RETRIEVE all loads: Submits GET request with no path parameters and no body in JSON format
        Returns: JSON response
            Success Status: 200 OK (loads listed)
            Failure Status:
                            405 (Non-GET/POST request)
    ------------------------------------------------------------------------------------------
    CREATE a load: Submits POST request with no path parameters and required body in JSON format
        JSON attributes:
            content (str) : content of load - required
            volume (int) : volume of the load - required
            price (int/float) : price of load - required
        Returns: JSON response
            Success Status: 201 (load created)
            Failure Status:
                            400 (missing attribute)
                            405 (Non-GET/POST request)
    """
    if request.method == 'GET':
        query = client.query(kind=constants.LOADS)
        total_loads = len(list(query.fetch()))
        q_limit = int(request.args.get("limit", "5"))
        q_offset = int(request.args.get("offset", "0"))
        l_iterator = query.fetch(limit=q_limit, offset=q_offset)
        pages = l_iterator.pages
        results = list(next(pages))

        if l_iterator.next_page_token:
            next_offset = q_offset + q_limit
            next_url = request.base_url + "?limit=" + str(
                q_limit) + "&offset=" + str(next_offset)
        else:
            next_url = None

        temp_loads_list = []
        for result in results:
            formatted = format_load(result)
            temp_loads_list.append(formatted)

        all_loads = {"loads": temp_loads_list,
                     "Total loads": total_loads}
        if next_url:
            all_loads["next"] = next_url

        return jsonify(all_loads)

    elif request.method == 'POST':
        content = request.get_json()

        # Not all required attributes present
        if len(content) != 3 or "content" not in content or "volume" not in content or "price" not in content:
            return ({
                        "Error": "The request object is missing required attributes"
                    }, 400)

        if type(content["price"]) == str:
            return ({
                        "Error": "Price must be of type int or float"
                    }, 400)

        if content["price"] < 0:
            return ({
                        "Error": "Price must be a positive value"
                    }, 400)

        # All required attributes given - proceed to create new_load
        new_load = datastore.entity.Entity(key=client.key(constants.LOADS))
        new_load.update(
            {
                "volume": content["volume"],
                "content": content["content"],
                "price": content["price"],
                "carrier": None
            }
        )
        client.put(new_load)
        formatted = format_load(new_load)
        return jsonify(formatted), 201


@app.route('/loads/<load_id>', methods=['GET', 'PATCH', 'PUT', 'DELETE'])
def load_specific(load_id):
    """
    Method to retrieve or delete a specific load 
    ------------------------------------------------------------------------------------------
    RETRIEVE an existing load: Submits GET request with load_id and no body in JSON format
        Path Parameters:
            load_id: ID of load as <id>
        Returns: JSON response
            Success Status: 200 (load retrieved)
            Failure Status: 404 (load not found with particular load_id)
    ------------------------------------------------------------------------------------------
        EDIT an existing load (PATCH): Submits PATCH request with load_id and required body in JSON format
        Path Parameters:
            load_id: ID of boat as <id>
        JSON attributes:
            content (str) : content of load - required
            volume (int) : volume of the load - required
            price (int/float) : price of load - required
        Returns: JSON response
            Success Status: 200 (load edited)
            Failure Status:
                            400 (Updating invalid attribute)
                            404 (No load with load_id exists)
                            405 (Not acceptable method)
    ------------------------------------------------------------------------------------------
    EDIT an existing load (PUT): Submits PUT request with load_id and required body in JSON format
        Path Parameters:
            load_id: ID of load as <id>
        JSON attributes:
            content (str) : content of load - required
            volume (int) : volume of the load - required
            price (int/float) : price of load - required
        Returns: JSON response
            Success Status: 200 (boat edited)
            Failure Status:
                            400 (Missing 3 required attributes)
                            404 (No load with load_id exists)
                            405 (Not acceptable method)
    ------------------------------------------------------------------------------------------
    DELETE an existing load: Submits DELETE request with load_id and no body in JSON format
        Path Parameters:
            load_id: ID of load as <id>
        Returns: 
            Success Status: No Body returned
                            204 No Content
            Failure Status: JSON Body with failure message returned
                            404 (load not found with particular load_id)
    """
    if request.method == 'GET':
        try:
            load_key = client.key(constants.LOADS, int(load_id))
            load = client.get(key=load_key)
            formatted = format_load(load)
            return jsonify(formatted)

        # Includes NoneType errors and invalid literals
        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "No load with this load_id exists"
                    }, 404)

    # Edit subset of a boat's attributes
    elif request.method == 'PATCH':
        if request.content_type == "application/json":
            content = request.get_json()

            allowed_changes = ["content", "volume", "price"]
            for attribute in content:
                if attribute not in allowed_changes:
                    return ({
                                "Error": "Updating invalid attribute"
                            }, 400)

            if "content" in content:
                try:
                    load_key = client.key(constants.LOADS, int(load_id))
                    load = client.get(key=load_key)
                    load.update({
                        "content": content["content"]
                    })
                    client.put(load)

                except (ValueError, TypeError, AttributeError):
                    return ({
                                "Error": "No load with this load_id exists"
                            }, 404)

            if "volume" in content:
                try:
                    load_key = client.key(constants.LOADS, int(load_id))
                    load = client.get(key=load_key)
                    load.update({
                        "volume": content["volume"]
                    })
                    client.put(load)

                except (ValueError, TypeError, AttributeError):
                    return ({
                                "Error": "No load with this load_id exists"
                            }, 404)

            if "price" in content:
                if type(content["price"]) == str:
                    return ({
                                "Error": "Price must be of type int or float"
                            }, 400)

                if content["price"] < 0:
                    return ({
                                "Error": "Price must be a positive value"
                            }, 400)
                try:
                    load_key = client.key(constants.LOADS, int(load_id))
                    load = client.get(key=load_key)
                    load.update({
                        "price": content["price"]
                    })
                    client.put(load)

                except (ValueError, TypeError, AttributeError):
                    return ({
                                "Error": "No load with this load_id exists"
                            }, 404)

            load_key = client.key(constants.LOADS, int(load_id))
            load = client.get(key=load_key)
            formatted = format_load(load)
            return jsonify(formatted), 200

    # Edit all of a specific boat's attributes
    elif request.method == 'PUT':
        if request.content_type == "application/json":
            content = request.get_json()

            if len(content) != 3 or "content" not in content or "volume" not in content or "price" not in content:
                return ({
                            "Error": "The request object is missing at least one of the required attributes"
                        }, 400)

            if type(content["price"]) == str:
                return ({
                            "Error": "Price must be of type int or float"
                        }, 400)

            if content["price"] < 0:
                return ({
                            "Error": "Price must be a positive value"
                        }, 400)

            try:
                load_key = client.key(constants.LOADS, int(load_id))
                load = client.get(key=load_key)
                load.update(
                    {
                        "content": content["content"],
                        "volume": content["volume"],
                        "price": content["price"]
                    }
                )
                client.put(load)
                formatted = format_load(load)
                return formatted

            except (ValueError, TypeError, AttributeError):
                return ({
                            "Error": "No load with this load_id exists"
                        }, 404)
        else:
            return ({
                        "Error": "Unsupported Media Type"
                    }, 415)

    elif request.method == 'DELETE':
        try:
            load_key = client.key(constants.LOADS, int(load_id))
            load = client.get(key=load_key)

            if load is None:
                return ({
                            "Error": "No load with this load_id exists"
                        }, 404)

            # Check all boats and delete from boats if found
            query = client.query(kind=constants.BOATS)
            results = list(query.fetch())
            for result in results:
                if result["loads"]:
                    temp_loads = result["loads"]
                    if result["loads"][0]["id"] == int(load_id):
                        temp_loads.remove(result["loads"][0])
                        result.update(
                            {
                                "name": result["name"],
                                "type": result["type"],
                                "length": result["length"],
                                "loads": temp_loads
                            }
                        )
                        client.put(result)
            client.delete(load_key)
            return '', 204

        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "No load with this load_id exists"
                    }, 404)


@app.route('/boats/<boat_id>/loads/<load_id>', methods=['PUT', 'DELETE'])
def boats_loads(boat_id, load_id):
    """
    Method to manage loads (Assign or Remove a load)
    ------------------------------------------------------------------------------------------
    Assigning a load: Submits PUT request with boat_id and load_id with no body
        Path Parameters:
            boat_id: ID of boat as <boat_id>
            load_id: ID of load as <load_id>
        Returns: 
            Success Status: 204 (No Body returned)
                boat_id and load_id exists (load is successfully assigned)
            Failure: JSON Body with failure message returned
                403 (Load is already assigned)
                404 (boat_id or load_id does not exist)
    ------------------------------------------------------------------------------------------
    Removing a load: Submits DELETE request with boat_id and load_id with no body
        Path Parameters:
            boat_id: ID of boat as <boat_id>
            load_id: ID of load as <load_id>
        Returns: 
            Success Status: 204 (No Body returned)
                boat_id and load_id exists (load is successfully unassigned to boat)
            Failure: JSON Body with failure message returned
                404 (boat_id or load_id does not exist)
    """
    if request.method == 'PUT':
        try:
            boat_key = client.key(constants.BOATS, int(boat_id))
            load_key = client.key(constants.LOADS, int(load_id))
            boat = client.get(key=boat_key)
            load = client.get(key=load_key)

            if boat is None or load is None:
                return ({
                            "Error": "The specified boat and/or load does not exist"
                        }, 404)

            # Load cannot be assigned to multiple boats
            query = client.query(kind=constants.BOATS)
            results = list(query.fetch())
            for result in results:
                for load_iter in result["loads"]:
                    if load_iter["id"] == load_id:
                        return ({
                                    "Error": "Forbidden: Load is already assigned"
                                }, 403)

            # Load already has a carrier
            if load["carrier"]:
                return ({
                            "Error": "Forbidden: Load is already assigned"
                        }, 403)

            # Update "loads" under boats
            add_load = {
                "id": int(load_id),
                "self": constants.LINK + "loads/" + load_id
            }

            current_load = boat["loads"]
            current_load.append(add_load)
            # Load is unassigned and both load_id/boat id exist:
            boat.update(
                {
                    "name": boat["name"],
                    "type": boat["type"],
                    "length": boat["length"],
                    "loads": current_load
                }
            )
            client.put(boat)

            # Update carrier under "loads"
            add_carrier = {
                "id": int(boat_id),
                "self": constants.LINK + "boats/" + boat_id
            }

            load.update(
                {
                    "content": load["content"],
                    "volume": load["volume"],
                    "price": load["price"],
                    "carrier": add_carrier
                }
            )
            client.put(load)
            return '', 204

        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "The specified boat and/or load does not exist"
                    }, 404)

    elif request.method == 'DELETE':
        try:
            boat_key = client.key(constants.BOATS, int(boat_id))
            load_key = client.key(constants.LOADS, int(load_id))
            boat = client.get(key=boat_key)
            load = client.get(key=load_key)

            if boat is None or load is None:
                return ({
                            "Error": "No load with this load_id is on the boat with this boat_id"
                        }, 404)

            updated_load = boat["loads"]
            for iter_load in updated_load:
                if str(iter_load["id"]) == str(load_id):
                    updated_load.remove(iter_load)
                    boat.update(
                        {
                            "name": boat["name"],
                            "type": boat["type"],
                            "length": boat["length"],
                            "loads": updated_load
                        }
                    )
                    client.put(boat)
                    load.update(
                        {
                            "content": load["content"],
                            "volume": load["volume"],
                            "price": load["price"],
                            "carrier": None
                        }
                    )
                    client.put(load)
                    return '', 204

            return ({
                        "Error": "No load with this load_id is on the boat with this boat_id"
                    }, 404)
        except (ValueError, TypeError, AttributeError):
            return ({
                        "Error": "No load with this load_id is on the boat with this boat_id"
                    }, 404)


def format_boat(boat_input):
    """
    Helper function to format into required format
        Parameters:
            boat_input (Entity/Dict) : boat object
        Returns:
            output (OrderedDict/Dict): boat object in required JSON format 
    """
    output = OrderedDict()

    output["id"] = boat_input.key.id
    output["name"] = boat_input["name"]
    output["type"] = boat_input["type"]
    output["length"] = boat_input["length"]
    output["owner"] = boat_input["owner"]
    output["loads"] = boat_input["loads"]
    output["self"] = constants.LINK + "boats/" + str(boat_input.id)

    return output


def format_load(load_input):
    """
    Helper function to format into required format
        Parameters:
            load_input (Entity/Dict) : load object
        Returns:
            output (OrderedDict/Dict): load object in required JSON format 
    """
    output = OrderedDict()

    output["id"] = load_input.key.id
    output["content"] = load_input["content"]
    output["volume"] = load_input["volume"]
    output["price"] = load_input["price"]
    output["carrier"] = load_input["carrier"]
    output["self"] = constants.LINK + "loads/" + str(load_input.id)

    return output


def format_user(user_input):
    """
    Helper function to format into required format
        Parameters:
            user_input (Entity/Dict) : user object
        Returns:
            output (OrderedDict/Dict): user object in required JSON format
    """
    output = OrderedDict()

    output["user_id"] = user_input["user_id"]
    output["first_name"] = user_input["first_name"]
    output["last_name"] = user_input["last_name"]

    return output


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
