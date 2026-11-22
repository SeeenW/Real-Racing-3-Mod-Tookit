//
//  alpha_colour.fsh
//
//  Created by vchau.
//  Copyright EA 2012. All rights reserved.
//

uniform lowp vec4 u_CurrentColour;

void main()
{
	gl_FragColor = u_CurrentColour;
}

