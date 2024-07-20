# trivia
A live multiplayer trivia game where questions are generated on the spot and users can bid for the subject of the next question

## How to run the app on local

Clone the repo:
```
git clone https://github.com/Mihaiii/trivia.git
```

Install the requirements:
```
pip install -r requirements.txt
```

Start the app:
```
uvicorn app:app
```

You'll get a message similar to "INFO:     Uvicorn running on http://127.0.0.1:8000 " in the console. Access that URL in the browser to open the app.

### Project:

There's a project associated with this repo: https://github.com/users/Mihaiii/projects/4 .

### The meaning of the card statuses

In the source code, there is a `Topic` class, referred to in this documentation as a "topic card." This is what is displayed in the UI (user interface) on the left panel. A topic card can have one of the following statuses, depending on its current state:

- pending - This is the initial status a topic card has. When a pending card is picked up, it's first sent to a LLM (large language model) in order to confirm the topic meets quality criterias (ex: it needs to be in english, it doesn't have to have sensitive content etc.). Only topics proposed by the humans will be validated by LLMs. If the LLM confirms that the the proposed topic is ok, the status of the card will become "computing". Otherwise, it becomes "failed".
- computing - Once a topic card has computing status, it's sent to an LLM to generate a trivia question and possible answers given the received topic. This process can take few seconds. When it finishes, we'll have status successful if all is ok or status failed, if the LLM failed to generate the question for some reason.
- failed - The card failed for some reason (either technical or the user proposed a topic that is not ok)
- successful - A topic card has status successful when it contains the LLM generated question and the options of that question.
