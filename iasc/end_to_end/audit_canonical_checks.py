"""Small final QA for exact canonical raw-input comparison, not sample counts."""
from pathlib import Path
import json
from audit_e2e import canon
def main():
    pairs=[('bool_vs_int',{'x':True},{'x':1},False),
           ('int_vs_float',{'x':1},{'x':1.0},False),
           ('false_vs_zero',{'x':False},{'x':0},False),
           ('field_order',{'a':1,'b':2},{'b':2,'a':1},True)]
    rows=[dict(case=name,expected_equal=expected,observed_equal=canon(left)==canon(right),
               ordinary_python_equal=left==right) for name,left,right,expected in pairs]
    assert all(row['expected_equal']==row['observed_equal'] for row in rows)
    out=Path(__file__).resolve().parent/'AUDIT_CANONICAL_QA.json'
    out.write_text(json.dumps({'passed':True,'qa_cases':len(rows),'formal_denominator':False,'results':rows},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'qa_cases':len(rows)}))
if __name__=='__main__':main()
