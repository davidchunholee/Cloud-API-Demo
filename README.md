# Users, Boats, Loads: API Spec
## https://hw9-leeda3.ue.r.appspot.com

# User Creation
You will need a Google login to interact with this API, as it utilizes Google’s oAuth 2.0 service.
1.	Follow welcome page (https://hw9-leeda3.ue.r.appspot.com) and login
2.	Upon login, you will be provided with a JWT. This is what you will use to make calls to protected endpoints (boats) which correspond with your unique ID presented.
3.	View the documentation for supported API endpoints in the documentation folder.

# Entity Relationships, Authentication, and Making Requests

## Relationships: Boat and Loads
Loads can exist as a separate entity from boats, seen from the Data Model section. Upon creation of a Load, the ‘carrier’ property is automatically set to null. You can create a relationship between a boat and a load, which would update the ‘carrier’ property and set it as the id of the corresponding boat. This can also be seen under the ‘loads’ property under a specific boat. Boats can have multiple loads, but a load can be only on one boat at a time. If you wish to remove the relationship between a boat and a load, it will set the ‘carrier’ property under the load to null and the load will be removed from the corresponding boat.

## Relationships: Users and Boats
Boats are a protected entity and can only be accessed if the proper JWT is provided along with the request. Boats can only be created, viewed, updated, or deleted with the associated JWT. Upon creation of a boat, the ‘owner’ property is automatically set to the user’s unique identifier (ID).

## Authentication: User Entity
Upon sign in, a random, 20-character state variable is generated and stored in the Datastore. This state variable gets sent to Google’s oAuth endpoint along with the program’s client ID. After the user consents to logging in via Google, an access code with the same state variable is sent. Once the state variable is verified and the client has verified this request, a POST request is sent back with the access code so Google can verify the client and pass on the JWT which will be used in this application. Note that the JWT expires, but a new one can be obtained by relogging into this website and using the newly presented JWT. 
The unique identifier for a user is the ID property obtained via the Google People API. This API provides a unique ID which is stored in the Datastore and will be used to validate access to protected endpoints. The google oAuth2 library is used in order to map this unique ID (now stored on the Datastore) with the JWT (specifically the id_token module). As long as the ID in the datastore matches the ID received from the requests sent through this library, it will allow access to protected endpoints.

## Making Requests
The different types of requests and endpoints possible with this API is presented in the table of contents. For unprotected endpoints, no authorization is needed. In order to access a protected endpoint, the request must be sent in the Header of the request with the ‘Key:Value’ pair as follows: ‘Authorization:Bearer {{Supplied JWT}}’. If using Postman, the JWT can be supplied under the ‘Auth’ section with the Type set to Bearer Token.

# Documentation
View the documentation folder for more information on data models and API specs. Postman collection and environment are available for testing in the documentation folder as well.
