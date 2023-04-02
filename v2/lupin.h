#ifndef LUPIN_H
# define LUPIN_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct node {
    char        *data;
    struct node *next;
    struct node *prev;
} node;

void    insertNode(node **list, char *content);
void    findNode(node *head, char *item);
void    deleteNode(node **list, char *content);
void    printList(node *head);

#endif