"""Manage NeuraTwin team accounts. Does not send invitations or email."""
import argparse
import getpass
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from neuratwin import cloud


def main():
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['create-user','set-role','list'])
    parser.add_argument('--email');parser.add_argument('--user-id')
    parser.add_argument('--role',choices=['viewer','operator','admin'],default='viewer')
    parser.add_argument('--disable',action='store_true')
    args=parser.parse_args()
    if args.action=='list':
        for member in cloud.rows('halo_members',{'select':'user_id,role,active','order':'created_at.asc'}):print(member)
        return
    if args.action=='create-user':
        if not args.email:parser.error('--email is required')
        password=getpass.getpass('New account password (not echoed): ')
        if len(password)<12:parser.error('Use at least 12 characters.')
        if password!=getpass.getpass('Confirm password: '):parser.error('Passwords did not match.')
        user=cloud.request('POST','/auth/v1/admin/users',payload={'email':args.email,'password':password,'email_confirm':True}).json()
        key=user.get('id') or user['user']['id']
    else:
        if not args.user_id:parser.error('--user-id is required')
        key=args.user_id
    existing=cloud.rows('halo_members',{'user_id':'eq.'+key},1)
    payload={'role':args.role,'active':not args.disable}
    if existing:cloud.request('PATCH','/rest/v1/halo_members',params={'user_id':'eq.'+key},payload=payload)
    else:cloud.request('POST','/rest/v1/halo_members',payload={'user_id':key,**payload})
    print('Membership saved:',key,args.role,'disabled' if args.disable else 'active')


if __name__=='__main__':main()
