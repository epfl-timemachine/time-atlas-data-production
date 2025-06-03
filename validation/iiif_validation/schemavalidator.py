#!/usr/bin/python

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError, SchemaError, best_match, relevance
import json
from os import sys, path
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))
from .error_processor import IIIFErrorParser

def printPath(pathObj, fields):
    path = ''
    for item in pathObj:
        if isinstance(item, int):
            path += u'[{}]'.format(item)
        else:
            path += u'/'    
            path += item

    path += '/[{}]'.format(fields)
    return path    

def filter_errors_non_relevant_of_timeatlas_rde(errors):

                
    # as the validation is pre-backend ingestion and HTTP dissemination, we can ignore the following error.
    errors = [err for err in errors if "does not match '^http.*$'" not in err.message]
    return errors

def validate(data:dict):
    with open('iiif_validation/iiif_3_0.json') as json_file:
        try:
            schema = json.load(json_file)
        except ValueError as err:
            print ('Failed to load JSON due to: {}'.format(err))
            raise

    try:
        validator = Draft7Validator(schema)
        results = validator.iter_errors(json.loads(data))
    except SchemaError as err:    
        print('Problem with the supplied schema:\n')
        print(err)
        raise

    okay = 1
    #print (best_match(results))
    errors = sorted(results, key=relevance)
    #errors = [best_match(results)]
    error = " "
    errorsJson = []
    if errors:
        if len(errors) == 1 and 'is not valid under any of the given schemas' in errors[0].message:
            errors = errors[0].context
        
        errors = filter_errors_non_relevant_of_timeatlas_rde(results)
        if len(errors) > 1:
            print('Validation Failed')
            # check to see if errors are relveant to IIIF asset
            errorParser = IIIFErrorParser(schema, json.loads(data))
            relevantErrors = []
            i = 0
            # Go through the list of errors and check to see if they are relevant
            # If the schema has a oneOf clause it will return errors for each oneOf 
            # possibility. The isValid will check the type to ensure its relevant. e.g.
            # if a oneOf possibility is of type Collection but we have passed a Manifest
            # then its safe to ignore the validation error.
            for err in errors:
                if errorParser.isValid(list(err.absolute_schema_path), list(err.absolute_path)):

                    # if it is valid we want a good error message so diagnose which oneOf is 
                    # relevant for the error we've found.
                    if err.absolute_schema_path[-1] == 'oneOf':
                        try:
                            err = errorParser.diagnoseWhichOneOf(list(err.absolute_schema_path), list(err.absolute_path))
                        except RecursionError as error:
                            print (error)
                            print ('Failed to diagnose error due to recursion error. Schema: {} IIIF path: {}'.format(err.absolute_schema_path, err.absolute_path))

                            relevantErrors.append(err)
                    if isinstance(err, ValidationError):    
                        relevantErrors.append(err)
                    else:
                        relevantErrors.extend(err)
                    

                i += 1
            # Remove dupes    
            seen_titles = set()    
            errors = []
            for errorDup in relevantErrors:
                errorPath = errorParser.pathToJsonPath(errorDup.path)
                if errorPath not in seen_titles:
                    errors.append(errorDup)
                    seen_titles.add(errorPath)
            errorCount = 1
            # Now create some useful messsages to pass on
            for err in errors:
                detail = ''
                if 'title' in err.schema:
                    detail = err.schema['title']
                description = ''    
                if 'description' in err.schema:
                    detail += ' ' + err.schema['description']
                context = err.instance
                if isinstance(context, dict):
                    for key in context:
                        if isinstance(context[key], list): 
                            context[key] = '[ ... ]'
                        elif isinstance(context[key], dict):
                            context[key] = '{ ... }'
                errorsJson.append({
                    'title': 'Error {} of {}.\n Message: {}'.format(errorCount, len(errors), err.message),
                    'detail': detail,
                    'description': description,
                    'path': printPath(err.path, err.message),
                    'context': context,
                    'error': err

                })
                #print (json.dumps(err.instance, indent=4))
                errorCount += 1
            okay = 0
    if okay != 1:
        print ('Validation Failed. Found {} errors.'.format(len(errorsJson)))
    error = ""
    return {
        'okay': okay,
        'warnings': [],
        'error': error,
        'errorList': errorsJson
    }

def json_path(absolute_path):
    path = '$'
    for elem in absolute_path:
        if isinstance(elem, int):
            path += '[' + str(elem) + ']'
        else:
            path += '.' + elem
    return path    

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print ('Usage:\n\t{} manifest'.format(sys.argv[0]))
        exit(-1)
    with open(sys.argv[1]) as json_file:
        print ('Loading: {}'.format(sys.argv[1])) 
        try:
            iiif_json = json.load(json_file)
        except ValueError as err:
            print ('Failed to load JSON due to: {}'.format(err))
            exit(-1)

    result = validate(json.dumps(iiif_json), '3.0', sys.argv[1])
    for error in result['errorList']:
        print ("Message: {}".format(error['title']))
        print (" **")
        print (" Json_path: {}".format(json_path(error['error'].absolute_path)))
        print (" Instance: {}".format(error['error'].instance))
        print (" Context: {}".format(error['error'].context))
