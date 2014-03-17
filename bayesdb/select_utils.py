#
#   Copyright (c) 2010-2014, MIT Probabilistic Computing Project
#
#   Lead Developers: Jay Baxter and Dan Lovell
#   Authors: Jay Baxter, Dan Lovell, Baxter Eaves, Vikash Mansinghka
#   Research Leads: Vikash Mansinghka, Patrick Shafto
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

import re
import utils
import numpy
import os
import pylab
import matplotlib.cm
import inspect
import operator
import ast

import utils
import functions
import data_utils as du
from pyparsing import *

def get_conditions_from_whereclause(whereclause, M_c, T):
  whereclause = whereclause.lower()
  print "parsing whereclause: ", whereclause


  ## ------------------------- whereclause grammar ----------------------------

  operation = oneOf("<= >= < > =")
  column_identifier = Word(alphanums, alphanums + "_")
  float_number = Regex(r'[-+]?[0-9]*\.?[0-9]+')
  value = Word(alphanums + "'.")

  and_literal = CaselessLiteral("and")

  similarity_literal = Regex(r'similarity\sto')
  probability_of_literal = Regex(r'probability\sof')
  predictive_probability_of_literal = Regex(r'predictive\sprobability\sof')
  typicality_literal = CaselessLiteral("typicality")

  probability_of_function = Group(probability_of_literal.setResultsName("fun_name")+ 
                                  column_identifier.setResultsName("column")+ 
                                  operation.setResultsName("operation") + 
                                  value.setResultsName("value"))
  predictive_probability_of_function = Group(predictive_probability_of_literal.setResultsName("fun_name") +
                                             column_identifier.setResultsName("column"))
  similarity_function = Group(similarity_literal.setResultsName("fun_name") + 
                              column_identifier.setResultsName("row_id"))
  typicality_function = Group(typicality_literal.setResultsName("fun_name"))



  function_literal = similarity_function | predictive_probability_of_function | typicality_function | probability_of_function

  single_where_clause = Group((function_literal | column_identifier) + 
                              operation.setResultsName("operation") + 
                              value.setResultsName("value"))

  where_clause = single_where_clause + ZeroOrMore(and_literal + single_where_clause)


  ## --------------------------------------------------------------------------------

  
  if len(whereclause) == 0:
    return
 
  ## Create conds: the list of conditions in the whereclause.
  ## List of (c_idx, op, val) tuples.
  conds = list() 

  ## Order matters: need <= and >= before < and > and =.
  operator_map = {'<=': operator.le, '<': operator.lt, '=': operator.eq, '>': operator.gt, '>=': operator.ge}

  top_level_parse = where_clause.parseString(whereclause)
  for inner_element in top_level_parse:
    if inner_element == 'and':
      pass
    op = operator_map[inner_element[1]]
   
    
    # value is last element in clause - to be matched on by the first
    raw_val = inner_element[2]
    print "raw_val", raw_val
    if utils.is_int(raw_val):
  
      val = int(raw_val)
    elif utils.is_float(raw_val):
      val = float(raw_val)
    else:
      ## val could have matching single or double quotes, which we can safely eliminate
      ## with the following safe (string literal only) implementation of eval
      val = ast.literal_eval(raw_val)

    # simple where column = value statement
    if type(inner_element[0]) is str:
      colname = inner_element[0]
      if M_c['name_to_idx'].has_key(colname.lower()):
        conds.append(((functions._column, M_c['name_to_idx'][colname.lower()]), op, val))
        continue
      raise utils.BayesDBParseError("Invalid where clause argument: could not parse '%s'" % colname)

    else:
      functon_parse = inner_element[0]
      
    
    if inner_element[0].fun_name=="similarity to":
      
      print "similarity"
      row_id = inner_element[0].row_id
      target_column = None #TODO grammar doesn't support with respect to yet, only int rows
      conds.append((functions._similarity, (row_id, target_column), op, val))
      
#      conds.append(((functions._similarity, functions.parse_similarity(colname, M_c, T)), op, val))
      continue

    elif inner_element[0] == "typicality":
      print "typicality"
#      colname = inner_element[0]
      conds.append(((functions._row_typicality, None), op, val)) 
      continue
    '''
    t = functions.parse_row_typicality(colname)
    if t is not None:
      conds.append(((functions._row_typicality, None), op, val))
      continue
    '''

    p = functions.parse_predictive_probability(colname, M_c)
    if p is not None:
      conds.append(((functions._predictive_probability, p), op, val))
      continue
    '''
    ## If none of above query types matched, then this is a normal column query.
    if colname.lower() in M_c['name_to_idx']:
      conds.append(((functions._column, M_c['name_to_idx'][colname.lower()]), op, val))
      continue
    '''
    raise utils.BayesDBParseError("Invalid where clause argument: could not parse '%s'" % colname)

  
  return conds

def is_row_valid(idx, row, where_conditions, M_c, X_L_list, X_D_list, T, backend):
  """Helper function that applies WHERE conditions to row, returning True if row satisfies where clause."""
  for ((func, f_args), op, val) in where_conditions:
    where_value = func(f_args, idx, row, M_c, X_L_list, X_D_list, T, backend)
    return op(where_value, val)
  return True

def get_queries_from_columnstring(columnstring, M_c, T, column_lists):
    """
    Iterate through the columnstring portion of the input, and generate the query list.
    queries is a list of (query_function, query_args, aggregate) tuples,
    where query_function is: row_id, column, probability, similarity.
    
    For row_id: query_args is ignored (so it is None).
    For column: query_args is a c_idx.
    For probability: query_args is a (c_idx, value) tuple.
    For similarity: query_args is a (target_row_id, target_column) tuple.
    """
    query_colnames = [colname.strip() for colname in utils.column_string_splitter(columnstring, M_c, column_lists)]
    queries = []
    for idx, colname in enumerate(query_colnames):
      #####################
      # Single column functions (aggregate)
      #####################
      c = functions.parse_column_typicality(colname, M_c)
      if c is not None:
        queries.append((functions._col_typicality, c, True))
        continue
        
      m = functions.parse_mutual_information(colname, M_c)
      if m is not None:
        queries.append((functions._mutual_information, m, True))
        continue

      d = functions.parse_dependence_probability(colname, M_c)
      if d is not None:
        queries.append((functions._dependence_probability, d, True))
        continue

      c = functions.parse_correlation(colname, M_c)
      if c is not None:
        queries.append((functions._correlation, c, True))
        continue

      p = functions.parse_probability(colname, M_c)
      if p is not None:
        queries.append((functions._probability, p, True))
        continue

      #####################
      ## Normal functions (of a cell)
      ######################
      s = functions.parse_similarity(colname, M_c, T)
      if s is not None:
        queries.append((functions._similarity, s, False))
        continue

      t = functions.parse_row_typicality(colname)
      if t is not None:
        queries.append((functions._row_typicality, None, False))
        continue

      p = functions.parse_predictive_probability(colname, M_c)
      if p is not None:
        queries.append((functions._predictive_probability, p, False))
        continue

      ## If none of above query types matched, then this is a normal column query.
      if colname.lower() in M_c['name_to_idx']:
        queries.append((functions._column, M_c['name_to_idx'][colname], False))
        continue

      raise utils.BayesDBParseError("Invalid where clause argument: could not parse '%s'" % colname)        

    ## Always return row_id as the first column.
    query_colnames = ['row_id'] + query_colnames
    queries = [(functions._row_id, None, False)] + queries
    
    return queries, query_colnames

def convert_row_from_codes_to_values(row, M_c):
  """
  Helper function to convert a row from its 'code' (as it's stored in T) to its 'value'
  (the human-understandable value).
  """
  ret = []
  for cidx, code in enumerate(row): 
    if not numpy.isnan(code) and not code=='nan':
      ret.append(du.convert_code_to_value(M_c, cidx, code))
    else:
      ret.append(code)
  return tuple(ret)

def filter_and_impute_rows(where_conditions, whereclause, T, M_c, X_L_list, X_D_list, engine, query_colnames,
                           impute_confidence, num_impute_samples):
    """
    impute_confidence: if None, don't impute. otherwise, this is the imput confidence
    Iterate through all rows of T, convert codes to values, filter by all predicates in where clause,
    and fill in imputed values.
    """
    filtered_rows = list()

    if impute_confidence is not None:
      t_array = numpy.array(T, dtype=float)
      infer_colnames = query_colnames[1:] # remove row_id from front of query_columns, so that infer doesn't infer row_id
      query_col_indices = [M_c['name_to_idx'][colname] for colname in infer_colnames]

    for row_id, T_row in enumerate(T):
      row_values = convert_row_from_codes_to_values(T_row, M_c) ## Convert row from codes to values
      if is_row_valid(row_id, row_values, where_conditions, M_c, X_L_list, X_D_list, T, engine): ## Where clause filtering.
        if impute_confidence is not None:
          ## Determine which values are 'nan', which need to be imputed.
          ## Only impute columns in 'query_colnames'
          for col_id in query_col_indices:
            if numpy.isnan(t_array[row_id, col_id]):
              # Found missing value! Try to fill it in.
              # row_id, col_id is Q. Y is givens: All non-nan values in this row
              Y = [(row_id, cidx, t_array[row_id, cidx]) for cidx in M_c['name_to_idx'].values() \
                   if not numpy.isnan(t_array[row_id, cidx])]
              code = utils.infer(M_c, X_L_list, X_D_list, Y, row_id, col_id, num_impute_samples,
                                 impute_confidence, engine)
              if code is not None:
                # Inferred successfully! Fill in the new value.
                value = du.convert_code_to_value(M_c, col_id, code)
                row_values = list(row_values)
                row_values[col_id] = value
                row_values = tuple(row_values)
        filtered_rows.append((row_id, row_values))
    return filtered_rows

def order_rows(rows, order_by, M_c, X_L_list, X_D_list, T, engine):
  """Input: rows are list of (row_id, row_values) tuples."""
  if not order_by:
      return rows
  ## Step 1: get appropriate functions. Examples are 'column' and 'similarity'.
  function_list = list()
  for orderable in order_by:
    assert type(orderable) == tuple and type(orderable[0]) == str and type(orderable[1]) == bool
    raw_orderable_string = orderable[0]
    desc = orderable[1]

    ## function_list is a list of
    ##   (f(args, row_id, data_values, M_c, X_L_list, X_D_list, engine), args, desc)
    
    s = functions.parse_similarity(raw_orderable_string, M_c, T)
    if s:
      function_list.append((functions._similarity, s, desc))
      continue

    c = functions.parse_row_typicality(raw_orderable_string)
    if c:
      function_list.append((functions._row_typicality, c, desc))
      continue

    p = functions.parse_predictive_probability(raw_orderable_string, M_c)
    if p is not None:
      function_list.append((functions._predictive_probability, p, desc))
      continue

    if raw_orderable_string.lower() in M_c['name_to_idx']:
      function_list.append((functions._column, M_c['name_to_idx'][raw_orderable_string.lower()], desc))
      continue

    raise utils.BayesDBParseError("Invalid query argument: could not parse '%s'" % raw_orderable_string)

  ## Step 2: call order by.
  rows = _order_by(rows, function_list, M_c, X_L_list, X_D_list, T, engine)
  return rows

def _order_by(filtered_values, function_list, M_c, X_L_list, X_D_list, T, engine):
  """
  Return the original data tuples, but sorted by the given functions.
  The data_tuples must contain all __original__ data because you can order by
  data that won't end up in the final result set.
  """
  if len(filtered_values) == 0 or not function_list:
    return filtered_values

  scored_data_tuples = list() ## Entries are (score, data_tuple)
  for row_id, data_tuple in filtered_values:
    ## Apply each function to each data_tuple to get a #functions-length tuple of scores.
    scores = []
    for (f, args, desc) in function_list:
      score = f(args, row_id, data_tuple, M_c, X_L_list, X_D_list, T, engine)
      if desc:
        score *= -1
      scores.append(score)
    scored_data_tuples.append((tuple(scores), (row_id, data_tuple)))
  scored_data_tuples.sort(key=lambda tup: tup[0], reverse=False)

  return [tup[1] for tup in scored_data_tuples]


def compute_result_and_limit(rows, limit, queries, M_c, X_L_list, X_D_list, T, engine):
  data = []
  row_count = 0

  # Compute aggregate functions just once, then cache them.
  aggregate_cache = dict()
  for query_idx, (query_function, query_args, aggregate) in enumerate(queries):
    if aggregate:
      aggregate_cache[query_idx] = query_function(query_args, None, None, M_c, X_L_list, X_D_list, T, engine)

  # Only return one row if all aggregate functions (row_id will never be aggregate, so subtract 1 and don't return it).
  assert queries[0][0] == functions._row_id
  if len(aggregate_cache) == len(queries) - 1:
    limit = 1

  # Iterate through data table, calling each query_function to fill in the output values.
  for row_id, row_values in rows:
    ret_row = []
    for query_idx, (query_function, query_args, aggregate) in enumerate(queries):
      if aggregate:
        ret_row.append(aggregate_cache[query_idx])
      else:
        ret_row.append(query_function(query_args, row_id, row_values, M_c, X_L_list, X_D_list, T, engine))
    data.append(tuple(ret_row))
    row_count += 1
    if row_count >= limit:
      break
  return data
