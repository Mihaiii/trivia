
# Trivia

## Authors
- Mihai Chirculescu: [https://github.com/Mihaiii]
- Mihai Dobrescu: [https://github.com/mihaidobrescu1111]

## Overview
This application is designed to manage a real-time interactive experience, allowing users to connect, answer questions, and accumulate points based on correct responses. The system includes a WebSocket-based backend to handle real-time communication and synchronization of state across clients.

## Configurations
To run this application, ensure you have the following configurations set:

**Application-Specific Settings**:
   - `QUESTION_COUNTDOWN_SEC`: Time in seconds for users to answer a question. Default is 50 seconds, but in production, it might be reduced to 18 or 20 seconds.
   - `KEEP_FAILED_TOPIC_SEC`: Number of seconds to display a failed topic in the UI before removing it. Default is 5 seconds.
   - `MAX_TOPIC_LENGTH_CHARS`: Maximum number of characters allowed for a user to write a topic. Default is 30 characters.
   - `MAX_NR_TOPICS_FOR_ALLOW_MORE`: Maximum number of topics in the queue before automatically adding more if users don't propose new ones. Default is 6.
   - `NR_TOPICS_TO_BROADCAST`: Number of topics to display in the UI. The actual list can contain more than this. Default is 5.
   - `BID_MIN_POINTS`: Minimum number of points required to place a bid on a topic in the UI. Default is 3 points.
   - `TOPIC_MAX_LENGTH`: Maximum length for user-provided topics to prevent malicious input. Default is 25 characters.
   - `MAX_NR_TOPICS`: Maximum number of topics allowed in the system. Default is 50.
   - `DUPLICATE_TOPIC_THRESHOLD`: Threshold for determining if a proposed topic is a duplicate of an existing one, with a value between 0 and 1. A value of 0.9 means that 90% similarity or more will flag the topic as a duplicate.


## Running the App Locally
To run the app locally, follow these steps:

1. **Clone the Repository**:
   ```
   git clone https://github.com/Mihaiii/trivia.git
   ```

2. **Install Dependencies**:
   Install the necessary packages:
   ```
   pip install -r requirements.txt
   ```

3. **Run the Server**:
   Start the application server:
   ```
   uvicorn app:app --port 8000
   ```

4. **Access the Application**:
   Open a browser and navigate to `http://localhost:8000` to access the application.

## What does the app do?
The application is structured to facilitate real-time interactions through WebSocket connections. It includes the following key features:

- **Real-Time Communication**: Uses WebSocket to broadcast questions, collect answers, and display results to connected clients.
- **Session Management**: Handles user sessions to track and manage user states, including points accumulation.
- **Dynamic Content Updates**: Users receive live updates without the need to refresh their pages, ensuring a seamless interactive experience.

## Code Overview

### Major Components

1. **WebSocket Management**
   - The application uses WebSockets for real-time communication. This includes:
     - **Connection Handling**: Managing client connections, including connecting and disconnecting users.
     - **Message Broadcasting**: Sending updates, such as new questions or results, to all connected clients.

2. **Session and State Management**
   - **User Sessions**: Each user has a session that keeps track of their state, such as their current points and which questions they've answered.
   - **Game State**: The application maintains the state of the current game, including active topics, past questions, and scores.

3. **Topic and Question Handling**
   - **Topic Submission**: Users can propose new topics, which are managed by the system to ensure diversity and quality.
   - **Question Management**: The application controls the timing and display of questions, ensuring users have a fair chance to answer within a set time limit.

4. **Scoring System**
   - **Point Allocation**: Points are awarded based on correct answers and the order of responses. The system ensures fair distribution of points and handles edge cases like ties.
   - **Bid System**: Users can bid points to have their proposed topics considered, which incentivizes participation.

### Key Functions and Methods

- **`on_connect` and `on_disconnect`**: Manage user connections to the WebSocket server.
- **`broadcast_next_topics`**: Sends the list of upcoming topics to all connected clients.
- **`compute_winners`**: Determines the winners based on correct answers and updates their scores.
- **`send_to_clients`**: Utility function for sending data to specific clients or broadcasting to all.

### Security Considerations
- The application ensures that only authenticated and authorized users can propose topics or answer questions, preventing abuse.
- Input validation and length restrictions are implemented to protect against malicious inputs.

### The meaning of the card statuses

In the source code, there is a `Topic` class, referred to in this documentation as a "topic card." This is what is displayed in the UI (user interface) on the left panel. A topic card can have one of the following statuses, depending on its current state:

- pending - This is the initial status a topic card has. When a pending card is picked up, it's first sent to a LLM (large language model) in order to confirm the topic meets quality criterias (ex: it needs to be in english, it doesn't have to have sensitive content etc.). Only topics proposed by the humans will be validated by LLMs. If the LLM confirms that the the proposed topic is ok, the status of the card will become "computing". Otherwise, it becomes "failed".
- computing - Once a topic card has computing status, it's sent to an LLM to generate a trivia question and possible answers given the received topic. This process can take few seconds. When it finishes, we'll have status successful if all is ok or status failed, if the LLM failed to generate the question for some reason.
- failed - The card failed for some reason (either technical or the user proposed a topic that is not ok)
- successful - A topic card has status successful when it contains the LLM generated question and the options of that question.
