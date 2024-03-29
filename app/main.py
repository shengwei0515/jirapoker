# -*- coding: utf-8 -*-
from flask import jsonify
from flask import Flask
from flask_pymongo import PyMongo
from flask import request
from werkzeug.exceptions import HTTPException
from flask_cors import CORS
from bson.objectid import ObjectId
import datetime
import json
import os
import logging.config

from config import JIRA_URL
from services.jira_client import jira_client
from services.mapping import customfield
from models.issue import Issue
from models.sprint import Sprint
from models.user import User
from lib.jira import JIRA
from jira.exceptions import JIRAError
from config import MONGO_URI
from config import MONGO_USERNAME
from config import MONGO_PASSWORD


class JSONEncoder(json.JSONEncoder):
    ''' extend json-encoder class'''
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime.datetime):
            return str(o)
        return json.JSONEncoder.default(self, o)


_PATH = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_PATH, 'logging.ini')
DEFAULT_LOG_CONFIG = os.path.abspath(_PATH)

logging.config.fileConfig(DEFAULT_LOG_CONFIG)
logger = logging.getLogger('flask')

app = Flask(__name__)
app.json_encoder = JSONEncoder
app.config.update(
    MONGO_URI=MONGO_URI,
    MONGO_USERNAME=MONGO_USERNAME,
    MONGO_PASSWORD=MONGO_PASSWORD,
)
mongo = PyMongo(app)
CORS(app)


@app.route('/api/auth/SignIn', methods=['POST'])
def sign_in():
    json_data = request.json

    jira_user = json_data['jiraUser']
    jira_token = json_data['jiraToken']
    jira_client_of_user = JIRA(JIRA_URL, basic_auth=(jira_user, jira_token))
    user_profile = jira_client_of_user.get_myself_user_profile()

    user = User()
    user.accountId = user_profile['accountId']
    user.userName = user_profile['key']
    user.avatarUrl = user_profile['avatarUrls']['48x48']

    return jsonify(user.__dict__)


@app.route('/api/issue/<board_name>/active-and-future-sprints', methods=['GET'])
def get_issues_in_active_and_future_sprints_in_board(board_name):
    sprint_names = jira_client.get_active_and_future_sprint_names_in_board(board_name)

    issues_in_active_and_future_sprints = []  # [{'sprint_A': ['issue_A', ...]}, {'sprintB': ['issue_C'...]}...]
    for sprint_name in sprint_names:
        _issues = jira_client.search_issues('sprint="{}" AND issuetype not in (Sub-task, 估點, Memo)'.format(sprint_name),
                                            startAt=0,
                                            maxResults=False)
        issues = []
        for _issue in _issues:
            issue_story_point = 0.0
            if customfield['story_point'] in _issue.raw['fields'].keys():
                issue_story_point = _issue.raw['fields'][customfield['story_point']]

            issue = Issue()
            issue.issueKey = _issue.key
            issue.url = JIRA_URL + '/browse/{}'.format(_issue.key)
            issue.summary = _issue.fields.summary
            issue.description = _issue.fields.description
            issue.storyPoint = issue_story_point
            issue.sprintName = sprint_name
            issues.append(issue.__dict__)

        sprint = Sprint()
        sprint.sprintName = sprint_name
        sprint.issues = issues

        issues_in_active_and_future_sprints.append(sprint.__dict__)
    return jsonify(issues_in_active_and_future_sprints)


@app.route('/api/issue/story-point', methods=['PUT'])
def update_story_point_in_jira():
    request_body = request.json

    issue = jira_client.issue(request_body['issueKey'])
    issue.update(fields={customfield['story_point']: request_body['storyPoint']})

    return 'Update story point successfully', 200


@app.route('/api/issue/estimation-result', methods=['POST'])
def insert_issue_estimation_result():
    request_body = request.json

    estimation_record_of_issue = mongo.db.estimation_result.find_one({'issueKey': request_body['issueKey'],
                                                                      'userName': request_body['userName']})
    if not estimation_record_of_issue:
        mongo.db.estimation_result.insert_one(request_body)
    else:
        estimation_record_of_issue.update({'estimatedStoryPoint': request_body['estimatedStoryPoint']})
        mongo.db.estimation_result.update_one({'_id': estimation_record_of_issue['_id']},
                                              {'$set': estimation_record_of_issue})

    return "OK", 200


@app.route('/api/issue/<issue_key>/estimation-results', methods=['GET'])
def get_issue_estimation_results(issue_key):
    issue_estimation_results = list(mongo.db.estimation_result.find({'issueKey': issue_key}, {'_id': False}))
    return jsonify(issue_estimation_results)


@app.errorhandler(Exception)
def handle_error(e):
    print(type(e))
    code = 500
    if isinstance(e, HTTPException):
        code = e.code
    elif isinstance(e, JIRAError):
        code = e.status_code
    logger.error('%s', str(e))
    return jsonify(error=str(e)), code


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=80)
